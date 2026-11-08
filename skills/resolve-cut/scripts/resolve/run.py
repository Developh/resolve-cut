#!/usr/bin/env python3
"""Run a script inside DaVinci Resolve Studio from the command line, without an MCP server.

    python3 run.py <script.py> '<json params>' [--project "Name"]
    python3 run.py render.py '{"phase": "status", "job": "<id>"}'
    python3 run.py - '{}' <<< 'result = project.GetName()'        # inline code from stdin

Connects to the running Resolve and runs the script with `resolve`, `project` and `P` (the JSON params) already
defined, the same names the official MCP's run_script_unsafe provides. Prints the script's `result` as JSON.

- --project: load this project first (the open one is saved); without it, the script gets the open project.
- The script also gets `__file__`, so it can find files next to it (render.py finds its presets this way).
- Needs DaVinci Resolve Studio running, with Preferences > System > General > External scripting using = Local.
  Since 21.1, the free edition does not accept external Python scripts.
- Finds Blackmagic's scripting module through RESOLVE_SCRIPT_API (defaults to the standard install path of this
  OS) and the Fusion library through RESOLVE_SCRIPT_LIB (optional, the module has its own defaults), from the
  environment or a .env file in the current folder.
- Exit code 2 when Resolve is not running or refuses external scripts.
"""
import json
import os
import sys


def load_dotenv(path=".env"):
    """KEY=value lines from ./.env fill variables the environment does not already have."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        name, _, value = line.strip().partition("=")
        name, value = name.strip(), value.strip().strip("\"'")
        if name and not name.startswith("#") and value:
            os.environ.setdefault(name, value)


def module_dir():
    api = os.environ.get("RESOLVE_SCRIPT_API")
    if not api:
        if sys.platform == "darwin":
            api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        elif sys.platform.startswith("win"):
            api = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                               "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
        else:
            api = "/opt/resolve/Developer/Scripting"
    return os.path.join(api, "Modules")


def fail(message):
    print(json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(2)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0 if args else 1)
    project_name = None
    if "--project" in args:
        k = args.index("--project")
        if k + 1 >= len(args):
            sys.exit("--project needs a project name")
        project_name = args[k + 1]
        del args[k:k + 2]
    script = args[0]
    params = json.loads(args[1]) if len(args) > 1 else {}
    code = sys.stdin.read() if script == "-" else open(script, encoding="utf-8").read()

    load_dotenv()
    sys.path.append(module_dir())
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        fail(f"DaVinciResolveScript not found in {module_dir()}: set RESOLVE_SCRIPT_API to Resolve's Developer/Scripting folder")
    resolve = dvr.scriptapp("Resolve")
    if not resolve or not resolve.GetProjectManager():
        fail("Resolve is not running or does not accept external scripts (Studio only; Preferences > System > General > External scripting using = Local)")
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project_name and (not project or project.GetName() != project_name):
        pm.SaveProject()
        project = pm.LoadProject(project_name)
        if not project:
            fail(f"could not open the project {project_name!r}")

    env = {"resolve": resolve, "project": project, "P": params, "result": None, "__name__": "__resolve__",
           "__file__": os.path.abspath(script) if script != "-" else "<stdin>"}
    exec(compile(code, script, "exec"), env)
    print(json.dumps(env.get("result"), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()

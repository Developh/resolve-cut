"""Source of assets/qr.png: the repository URL as a QR code, dark on white, error correction Q.

    python3 assets/src/qr.py            # needs: python3 -m pip install "qrcode[pil]"
    # then decode it (zbarimg --raw assets/qr.png, or OpenCV's QRCodeDetector) and compare with URL
"""
import os

import qrcode

URL = "https://github.com/tiagonrodrigues/davinci-resolve-agent"
qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=24, border=4)
qr.add_data(URL)
qr.make(fit=True)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "qr.png")
qr.make_image(fill_color="#0b0b0b", back_color="#ffffff").save(out)
print(os.path.normpath(out), f"version {qr.version}, {qr.modules_count} modules")

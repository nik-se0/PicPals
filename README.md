# PicPals
__Picture Pals – the Image Collection Tidying Utility & Recognition Engine🐾__

This program is both your photography and labeling assistant! 
With Picture Pals you can:
* Group images by similarity or date
* Hunt down and delete blurry shots
* Spot screenshots and photos packed with text

Just fire it up, point it to a folder, and let your pals whip your photo library into shape!

### Run from the command line:
```bash
cmd
cd /d "C:\Path\To\Your\Project"
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install pyinstaller pillow opencv-python imagehash numpy colorama pywin32
pyinstaller --onefile --hidden-import=cv2 --hidden-import=cv2.cv2 --hidden-import=imagehash --hidden-import=pywt --console --icon=app.ico Photo.py
cd dist
Photo.exe
```

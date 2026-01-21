import os, zipfile, sys
if len(sys.argv)<2:
    print("Usage: python tools/restore_axis.py <backup.zip>"); sys.exit(1)
zip_path = sys.argv[1]
with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall(".")
print("Restored from", zip_path)

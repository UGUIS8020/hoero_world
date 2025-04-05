# zip_handler.py
import os
import zipfile
import shutil
from datetime import datetime, timedelta
import threading
import time
from werkzeug.utils import secure_filename

class ZipHandler:
    def __init__(self, upload_folder='uploads', temp_zip_folder='temp_zips'):
        self.UPLOAD_FOLDER = upload_folder
        self.TEMP_ZIP_FOLDER = temp_zip_folder
        
        # ディレクトリの作成
        os.makedirs(self.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(self.TEMP_ZIP_FOLDER, exist_ok=True)   

    def process_files(self, files):
        """ファイルを処理してZIPファイルを作成"""
        if not files:
            raise ValueError('ファイルが選択されていません')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_dir = os.path.join(self.TEMP_ZIP_FOLDER, timestamp)
        os.makedirs(temp_dir, exist_ok=True)

        try:
            if len(files) <= 10:
                print("Saving files without compression")
                saved_files = []
                for file in files:
                    filename = secure_filename(file.filename)
                    save_path = os.path.join(temp_dir, filename)
                    file.save(save_path)
                    saved_files.append(save_path)
                # 一時ディレクトリは削除せず、呼び出し元で削除する
                return saved_files, temp_dir
            else:
                print("Creating compressed zip")
                zip_path = os.path.join(self.TEMP_ZIP_FOLDER, f'compressed_{timestamp}.zip')
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in files:
                        print(f"Processing file: {file.filename}")
                        filename = secure_filename(file.filename)
                        temp_path = os.path.join(temp_dir, filename)
                        file.save(temp_path)
                        zipf.write(temp_path, filename)
                
                # ZIPファイル作成後、一時ディレクトリを削除
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                
                return zip_path, None
        except Exception as e:
            # エラー発生時は一時ディレクトリを削除
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
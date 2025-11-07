"""
utils/oralscan_bot.py
Oral Scan Data 自動ログイン機能
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import os
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()


def run_oralscan_login(headless=True, keep_browser_open=False):
    """
    Oral Scan Data ウェブサイトにログインして症例一覧ページに移動
    
    Args:
        headless (bool): ヘッドレスモードで実行するか（デフォルト: True）
        keep_browser_open (bool): ブラウザを開いたままにするか（デフォルト: False）
    
    Returns:
        bool: 成功したらTrue、失敗したらFalse
    """
    
    # 環境変数から認証情報を取得
    EMAIL = os.getenv('ORALSCAN_EMAIL')
    PASSWORD = os.getenv('ORALSCAN_PASSWORD')
    
    if not EMAIL or not PASSWORD:
        print("❌ 環境変数 ORALSCAN_EMAIL と ORALSCAN_PASSWORD が設定されていません")
        return False
    
    # Chromeオプションの設定
    chrome_options = Options()
    
    if headless:
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
    
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # サーバー環境用の追加オプション
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-infobars')
    
    driver = None
    
    try:
        # WebDriverの初期化
        driver = webdriver.Chrome(options=chrome_options)
        
        print("🌐 ウェブサイトにアクセスしています...")
        driver.get("https://jp.oralscandata.com/#/login")
        time.sleep(3)
        
        print("🔍 ログインフォームを探しています...")
        wait = WebDriverWait(driver, 10)
        
        # メールアドレス入力
        email_field = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='メール']"))
        )
        email_field.clear()
        email_field.send_keys(EMAIL)
        print(f"✓ メールアドレスを入力")
        
        # パスワード入力
        password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        password_field.clear()
        password_field.send_keys(PASSWORD)
        print("✓ パスワードを入力")
        
        time.sleep(0.5)
        
        # チェックボックス（もしあれば）
        try:
            checkbox = driver.find_element(By.CSS_SELECTOR, "label.el-checkbox")
            if checkbox:
                checkbox.click()
                print("✓ チェックボックスをクリック")
        except:
            pass
        
        # ログインボタンをクリック
        login_button = driver.find_element(By.CSS_SELECTOR, "button.el-button--primary")
        driver.execute_script("arguments[0].click();", login_button)
        print("✓ ログインボタンをクリック")
        
        # ログイン処理を待機
        time.sleep(5)
        
        current_url = driver.current_url
        
        if "login" not in current_url.lower():
            print("✅ ログインに成功しました!")
            
            # 症例一覧ページに移動
            print("📋 症例一覧ページに移動中...")
            driver.get("https://jp.oralscandata.com/#/order/list")
            time.sleep(3)
            
            print(f"✓ 症例一覧ページに到達: {driver.current_url}")
            
            # スクリーンショットを保存（オプション）
            try:
                screenshot_path = os.path.join(os.getcwd(), 'static', 'screenshots', 'oralscan_last_run.png')
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                driver.save_screenshot(screenshot_path)
                print(f"✓ スクリーンショットを保存: {screenshot_path}")
            except Exception as e:
                print(f"⚠️  スクリーンショット保存失敗: {str(e)}")
            
            if not keep_browser_open and driver:
                driver.quit()
            
            return True
        else:
            print("❌ ログインに失敗しました")
            if driver:
                driver.quit()
            return False
    
    except Exception as e:
        print(f"❌ エラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        if driver:
            try:
                driver.quit()
            except:
                pass
        return False


if __name__ == "__main__":
    # スタンドアロンで実行する場合
    print("="*60)
    print(" Oral Scan Data 自動ログイン")
    print("="*60)
    print()
    
    success = run_oralscan_login(headless=False, keep_browser_open=True)
    
    if success:
        print("\n✅ 処理が完了しました")
    else:
        print("\n❌ 処理に失敗しました")
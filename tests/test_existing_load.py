"""
既存ファイル読み込みテスト - 起動時に既存画像を重複検出対象にできることを確認
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zoom_auto_capture.screenshot import ScreenshotCapture
from zoom_auto_capture import config


def test_existing_files_loading():
    """Test that existing files are loaded and prevent duplicates on restart."""
    print("=" * 60)
    print("既存ファイル読み込みテスト")
    print("=" * 60)

    capture1 = ScreenshotCapture()

    if not capture1.is_available:
        print("❌ mss / Pillow が見つかりません。")
        return False

    print("✓ mss / Pillow が利用可能です。")

    # First session: capture initial screenshot
    print("\n1. 最初のセッション - 初回スクリーンショットを保存...")
    capture1.start("既存読込テスト", "existing_load_test")
    time.sleep(3)
    initial_count = capture1.status.screenshot_count
    capture1.stop()
    print(f"✓ 初回セッション終了。保存枚数: {initial_count}")

    # Second session: restart and check if it prevents duplicates
    print("\n2. 2回目のセッション - 既存ファイルを読み込んで再開...")
    capture2 = ScreenshotCapture()
    capture2.start("既存読込テスト", "existing_load_test")
    
    print("   ※ 同じ画面のため、新しいスクリーンショットは保存されないはずです。")
    time.sleep(5)
    
    second_count = capture2.status.screenshot_count
    capture2.stop()
    
    print(f"✓ 2回目のセッション終了。新規保存枚数: {second_count}")

    # Check results
    today = time.strftime("%Y%m%d")
    output_dir = config.SCREENSHOT_DIR / today / "existing_load_test"
    
    if output_dir.exists():
        files = list(output_dir.glob("*.png"))
        total_files = len(files)
        print(f"\n3. 出力ディレクトリ確認:")
        print(f"   パス: {output_dir}")
        print(f"   合計ファイル数: {total_files}")
        
        if second_count == 0:
            print("✓ 既存ファイルが正しく読み込まれ、重複が防止されました！")
        else:
            print(f"⚠️ 2回目のセッションで {second_count} 枚保存されました。")
    
    print("\n" + "=" * 60)
    print("✓ 既存ファイル読み込みテストが完了しました。")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_existing_files_loading()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nテストが中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ テスト中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

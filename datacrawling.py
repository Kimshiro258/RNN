import requests
import os
import threading
import time
import subprocess
import sys
from urllib.parse import urljoin


# -------------------------- 配置项（根据自己环境修改） --------------------------
# 自动查找 FFmpeg 可执行文件路径
def find_ffmpeg():
    import shutil

    # 1. 检查系统 PATH 中的 ffmpeg
    path_ffmpeg = shutil.which('ffmpeg')
    if path_ffmpeg:
        return path_ffmpeg

    # 2. 检查常见的安装路径
    common_paths = [
        "/opt/homebrew/bin/ffmpeg",  # macOS Homebrew
        "/usr/local/bin/ffmpeg",  # macOS/Linux
        "/usr/bin/ffmpeg",  # Linux
        "C:\\ffmpeg\\bin\\ffmpeg.exe",  # Windows
        os.path.join(os.path.dirname(sys.executable), "ffmpeg"),  # 虚拟环境
        os.path.join(os.path.dirname(sys.executable), "Scripts", "ffmpeg.exe"),  # Windows 虚拟环境
    ]

    for path in common_paths:
        if os.path.exists(path):
            return path

    # 3. 如果都找不到，返回默认
    return "ffmpeg"


FFMPEG_BIN = find_ffmpeg()
print(f"🔍 使用的 FFmpeg 路径: {FFMPEG_BIN}")

THREAD_MAX = 10
RETRY_TIMES = 3
M3U8_URL = "https://tx-safety-video.acfun.cn/mediacloud/acfun/acfun_video/a0ec81e03cf029fb-0e210ce522bc7d0837ea6e79d21764af-hls_360p_hevc_1.m3u8?pkey=ABB_syzvmfgBZ59il26ZwUCvbcFylpG4qMZNeO4V3vqaRCxWKFclocjGLDBzg1uVHm_-UqO2VEqUTigtnN4c2jK25jKvphDncvAEwfiL9qCbiLaK3T154V7WdQ-6y2IfgxR2QHzXbCJCjb-ynCKqdJcnVVyz7RbHm0IiCxRHRnIFZYm6DzWEfXIZ4W4Uz7PtCwb_x5C-cwQA-yoJD9cdFJYtFq0Gt5DJ99jhfwvRYe6FxibJ9j2Jwlr8So_cXY4gv1w&safety_id=AAJ2cIX3KA7MBJfPxxGJFmVo"
SAVE_DIR = "./acfun_video"


# ------------------------------------------------------------------------------

# 基础下载函数
def download(url, name):
    headers = {
        'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'Referer': 'https://www.acfun.cn/v/ac48194793',
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            with open(name, 'wb') as f:
                f.write(r.content)
            # 校验下载文件是否为空（避免空TS文件）
            if os.path.getsize(name) == 0:
                os.remove(name)
                print(f'[失败] 下载的文件为空：{name}')
            else:
                print(f'[下载成功] {name}')
        else:
            print(f'[失败] 状态码 {r.status_code}:{url}')
    except Exception as e:
        print(f'[异常] {url}: {str(e)}')


# m3u8解析函数
def parse_m3u8(m3u8_url, m3u8_local):
    ts_list = []
    # 指定utf-8编码，避免不同系统读取乱码
    with open(m3u8_local, "r", encoding='utf-8') as f:
        lines = f.readlines()

    count = 0
    for line_num, line in enumerate(lines, 1):  # 行号从1开始
        line = line.strip()
        if line.startswith("#") or not line:  # 跳过注释和空行
            continue

        if ".ts" in line:
            count += 1
            full_url = urljoin(m3u8_url, line)  # 拼接完整URL
            local_name = f"ts_segment_{count:04d}.ts"  # 有序的本地文件名
            ts_list.append((count, line_num, line, full_url, local_name))
    return ts_list


# TS分片多线程下载函数
def m3u8_download_multi_thread(m3u8_url, save_dir, thread_max=10, retry_times=3):
    # 创建ts分片保存目录
    ts_dir = os.path.join(save_dir, "ts")
    os.makedirs(ts_dir, exist_ok=True)

    # 1. 下载m3u8文件到本地
    m3u8_local = os.path.join(save_dir, "index.m3u8")
    download(m3u8_url, m3u8_local)

    # 2. 解析m3u8得到ts分片列表
    ts_list = parse_m3u8(m3u8_url, m3u8_local)
    total_ts = len(ts_list)
    if total_ts == 0:
        print("⚠️ 未解析到任何TS分片，下载终止")
        return total_ts, []  # 返回总分片数、失败列表

    # 记录失败的TS分片
    failed_ts = []

    # 带重试的TS下载子函数
    def download_ts_with_retry(ts_url, save_path, retry):
        for attempt in range(1, retry + 1):
            try:
                headers = {
                    'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
                    'Referer': 'https://www.acfun.cn/v/ac48194793',
                }
                r = requests.get(ts_url, headers=headers, timeout=15)
                if r.status_code == 200:
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    # 校验文件是否为空
                    if os.path.getsize(save_path) == 0:
                        raise Exception("文件下载后为空")
                    print(f"✅ [成功] 分片 {save_path.split('/')[-1]} (第{attempt}次尝试)")
                    return True
                else:
                    raise Exception(f"状态码 {r.status_code}")
            except Exception as e:
                if attempt == retry:
                    print(f"❌ [失败] 分片 {save_path.split('/')[-1]} (重试{retry}次后仍失败)：{str(e)}")
                    failed_ts.append((ts_url, save_path))
                    return False
                print(f"⚠️ [重试] 分片 {save_path.split('/')[-1]} (第{attempt}次失败，即将重试)：{str(e)}")
                time.sleep(1)  # 重试前等待1秒

    # 启动多线程下载
    print(f"\n🚀 开始下载{total_ts}个TS分片，最大并发线程数：{thread_max}")
    for idx, (count, line_num, ts_rel, ts_url, local_name) in enumerate(ts_list):
        # 控制最大并发数（排除主线程）
        while threading.active_count() - 1 >= thread_max:
            time.sleep(0.5)

        save_path = os.path.join(ts_dir, local_name)
        print(f"📥 [队列 {idx + 1}/{total_ts}] 开始下载分片：{local_name}")
        # 启动子线程
        threading.Thread(
            target=download_ts_with_retry,
            args=(ts_url, save_path, retry_times)
        ).start()

    # 等待所有下载线程完成
    print(f"\n⏳ 等待所有TS分片下载完成...")
    while threading.active_count() > 1:
        time.sleep(1)

    # 下载完成汇总
    success_count = total_ts - len(failed_ts)
    print(f"\n==================== 下载汇总 ====================")
    print(f"总分片数：{total_ts} | 成功：{success_count} | 失败：{len(failed_ts)}")
    if failed_ts:
        print(f"\n❌ 失败的TS分片列表：")
        for ts_url, save_path in failed_ts:
            print(f"  - {save_path.split('/')[-1]}: {ts_url}")
    else:
        print(f"\n🎉 所有TS分片下载完成，保存到：{ts_dir}")

    return total_ts, failed_ts  # 返回总分片数、失败列表


# TS分片合并为MP4函数 - 直接使用subprocess调用FFmpeg
def merge_ts_to_mp4(save_dir, total_ts, failed_ts):
    # 1. 前置校验：有失败分片则终止合并
    if len(failed_ts) > 0:
        print(f"\n❌ 检测到{len(failed_ts)}个失败的TS分片，无法合并完整视频，请先修复下载！")
        return

    # 2. 路径配置
    ts_dir = os.path.abspath(os.path.join(save_dir, "ts"))  # TS分片目录
    output_mp4 = os.path.abspath(os.path.join(save_dir, "final_video.mp4"))  # 最终视频文件名

    # 3. 按数字顺序排序TS文件（保证合并顺序正确）
    try:
        ts_files = [os.path.join(ts_dir, f) for f in os.listdir(ts_dir) if f.endswith(".ts")]
        # 提取文件名中的数字（ts_segment_0001.ts → 1），按数值排序
        ts_files = sorted(
            ts_files,
            key=lambda x: int(os.path.splitext(os.path.basename(x))[0].split("_")[-1])
        )
    except Exception as e:
        print(f"⚠️ TS文件排序失败：{str(e)}，将使用默认排序")
        ts_files = sorted([os.path.join(ts_dir, f) for f in os.listdir(ts_dir) if f.endswith(".ts")])

    # 4. 校验TS文件数量
    if not ts_files:
        print("⚠️ 未找到任何TS分片，无法合并")
        return
    if len(ts_files) != total_ts:
        print(f"\n⚠️ 检测到TS文件数量({len(ts_files)})与解析的分片数({total_ts})不匹配，合并可能失败！")

    # 5. 使用subprocess调用FFmpeg进行合并
    print(f"\n📽️ 开始合并{len(ts_files)}个TS分片为MP4：{output_mp4}")

    # 创建临时文件列表
    list_file = os.path.join(ts_dir, "filelist.txt")
    try:
        with open(list_file, 'w', encoding='utf-8') as f:
            for ts_file in ts_files:
                f.write(f"file '{ts_file}'\n")

        # 构建 FFmpeg 命令
        cmd = [
            FFMPEG_BIN,
            '-f', 'concat',
            '-safe', '0',
            '-i', list_file,
            '-c', 'copy',  # 直接复制编码，不重新编码（速度快）
            '-bsf:a', 'aac_adtstoasc',  # 修复音频ADTS头，解决无声音问题
            '-y',  # 覆盖已存在的文件
            output_mp4,
            '-hide_banner'  # 隐藏ffmpeg冗余日志
        ]

        # 执行命令
        print(f"🔧 执行命令：{' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )

        if result.returncode == 0:
            print(f"✅ 合并成功！最终视频已保存到：{output_mp4}")
            print(f"📊 FFmpeg输出：{result.stdout}")
        else:
            print(f"❌ 合并失败！错误信息：")
            print(f"FFmpeg错误输出：{result.stderr}")
            return False

    except FileNotFoundError:
        print(f"❌ 未找到FFmpeg可执行文件，请检查FFMPEG_BIN配置是否正确（当前：{FFMPEG_BIN}）")
        print("请确保已安装FFmpeg并添加到系统PATH，或修改FFMPEG_BIN为正确路径")
        return False
    except Exception as e:
        print(f"❌ 合并失败：{str(e)}")
        return False
    finally:
        # 清理临时文件
        if os.path.exists(list_file):
            os.remove(list_file)
            print(f"🧹 已清理临时文件：{list_file}")

    return True


# 主函数（流程闭环：下载TS → 合并MP4）
if __name__ == '__main__':
    # 1. 创建保存目录
    os.makedirs(SAVE_DIR, exist_ok=True)

    # 2. 多线程下载TS分片
    total_ts, failed_ts = m3u8_download_multi_thread(
        m3u8_url=M3U8_URL,
        save_dir=SAVE_DIR,
        thread_max=THREAD_MAX,
        retry_times=RETRY_TIMES
    )

    # 3. 合并TS分片为完整MP4
    if total_ts > 0:
        success = merge_ts_to_mp4(SAVE_DIR, total_ts, failed_ts)
        if success:
            print(f"\n🎉 视频下载和合并全部完成！")
        else:
            print(f"\n⚠️ 视频合并失败，请检查错误信息")

    print("\n📌 流程结束！")
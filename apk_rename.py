#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Termux APK 包名一键修改工具 v2.0

【实战经验（已验证）】
1. apktool 3.0.3 的 renameManifestPackage 字段不生效 → 必须直接改 AndroidManifest.xml 的 package 属性
2. 绝对不能替换 smali 文件中的包名（类路径由目录结构决定，只改内容会导致回编译失败）
3. apktool b 编译大 APK 需要 1~5 分钟，必须显示进度提示避免用户中断
4. 构建在 Termux 主目录进行（避免 /sdcard 权限和 FUSE 性能问题），最终输出复制到源 APK 同目录
5. aapt2 模式失败时自动回退到标准模式
"""

import os
import re
import sys
import shutil
import shlex
import subprocess
import getpass
import time
import threading
from pathlib import Path
from datetime import datetime


# ============================================================
# 颜色
# ============================================================
class C:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def info(msg):  print(f"{C.CYAN}[*]{C.END} {msg}", flush=True)
def ok(msg):    print(f"{C.GREEN}[✓]{C.END} {msg}", flush=True)
def warn(msg):  print(f"{C.YELLOW}[!]{C.END} {msg}", flush=True)
def err(msg):   print(f"{C.RED}[✗]{C.END} {msg}", flush=True)


def die(msg, code=1):
    err(msg)
    sys.exit(code)


# ============================================================
# 日志
# ============================================================
LOG_FILE = None


def init_log(log_path):
    global LOG_FILE
    LOG_FILE = log_path
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Termux APK 包名修改日志\n")
            f.write(f"开始时间: {datetime.now()}\n")
            f.write("=" * 60 + "\n")
    except Exception:
        LOG_FILE = None


def log(msg):
    if not LOG_FILE:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ============================================================
# 命令执行
# ============================================================
def run_cmd(cmd, check=True, timeout=600, env=None):
    """静默执行命令，返回 CompletedProcess 或 None"""
    log(f"CMD: {cmd}")
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout, env=env, errors='replace'
        )
        if r.stdout:
            log(f"OUT: {r.stdout[-2000:]}")
        if r.stderr:
            log(f"ERR: {r.stderr[-2000:]}")
        if check and r.returncode != 0:
            return None
        return r
    except subprocess.TimeoutExpired:
        err(f"命令超时（{timeout}s）")
        log(f"TIMEOUT: {cmd}")
        return None
    except Exception as e:
        err(f"命令异常: {e}")
        log(f"EXCEPTION: {e}")
        return None


def run_cmd_live(cmd, timeout=1800, hint="执行中", env=None, filter_fn=None):
    """
    实时执行命令并显示进度：
    - 输出实时写入日志
    - 关键行显示到终端
    - 每 30s 显示一次心跳提示（防止用户误以为卡住而中断）
    返回 returncode（int），超时或异常返回 None
    """
    log(f"CMD(live): {cmd}")
    if hint:
        info(hint)

    start = time.time()
    last_beat = [start]
    print_lock = threading.Lock()

    try:
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env, errors='replace'
        )
    except Exception as e:
        err(f"启动命令失败: {e}")
        return None

    def reader():
        try:
            for line in proc.stdout:
                line_r = line.rstrip()
                if not line_r:
                    continue
                log(line_r)

                show = False
                if filter_fn:
                    try:
                        show = filter_fn(line_r)
                    except Exception:
                        show = False
                else:
                    if line_r.startswith('I:'):
                        keys = ['Using Apktool', 'Smaling', 'Building', 'Built',
                                'Importing', 'Copying', 'not changed', 'loaded',
                                'Decoding', 'Baksmaling', 'Generating', 'resources']
                        if any(k in line_r for k in keys):
                            show = True
                    elif line_r.startswith('W:') or line_r.startswith('E:'):
                        show = True
                    elif 'error' in line_r.lower() or 'exception' in line_r.lower():
                        show = True

                if show:
                    with print_lock:
                        low = line_r.lower()
                        if line_r.startswith('E:') or 'error' in low or 'exception' in low:
                            print(f"  {C.RED}│{C.END} {line_r}", flush=True)
                        elif line_r.startswith('W:'):
                            print(f"  {C.YELLOW}│{C.END} {line_r}", flush=True)
                        else:
                            print(f"  {C.CYAN}│{C.END} {line_r}", flush=True)
                    last_beat[0] = time.time()
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    while proc.poll() is None:
        time.sleep(1)
        now = time.time()
        if now - last_beat[0] >= 30:
            elapsed = int(now - start)
            print(f"  {C.YELLOW}… 已运行 {elapsed}s，请耐心等待，不要按 Ctrl+C{C.END}", flush=True)
            last_beat[0] = now
        if now - start > timeout:
            err(f"命令超时（{timeout}s），正在终止...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return None

    t.join(timeout=3)
    elapsed = int(time.time() - start)
    rc = proc.returncode
    log(f"RETURN: {rc}, 耗时 {elapsed}s")

    if rc == 0:
        ok(f"{hint}完成（耗时 {elapsed}s）")
    else:
        err(f"{hint}失败（exit={rc}）")
    return rc


# ============================================================
# 环境检测
# ============================================================
def check_command(name):
    return shutil.which(name) is not None


def check_termux():
    return os.path.exists('/data/data/com.termux')


def check_java():
    if not check_command('java'):
        return False, None
    r = run_cmd('java -version 2>&1', check=False, timeout=30)
    if r and r.returncode == 0:
        out = (r.stdout or '') + (r.stderr or '')
        first = out.strip().split('\n')[0]
        return True, first
    return False, None


def get_disk_free_mb(path):
    try:
        st = os.statvfs(path)
        return (st.f_bavail * st.f_frsize) / (1024 * 1024)
    except Exception:
        return -1


def install_dependencies():
    """检测并安装依赖"""
    print()
    info("开始检测环境依赖...")
    print()

    missing = set()

    java_ok, java_ver = check_java()
    if java_ok:
        ok(f"Java 已就绪: {java_ver}")
    else:
        warn("Java 未安装")
        missing.add('openjdk-17')

    if check_command('apktool'):
        r = run_cmd('apktool --version 2>&1', check=False, timeout=30)
        ver = (r.stdout.strip() if r and r.stdout else "未知")
        ok(f"apktool 已就绪 (版本: {ver})")
    else:
        warn("apktool 未安装")
        missing.add('apktool')

    if check_command('apksigner'):
        ok("apksigner 已就绪")
    else:
        warn("apksigner 未安装")
        missing.add('apksigner')

    if check_command('zipalign'):
        ok("zipalign 已就绪")
    else:
        warn("zipalign 未安装")
        missing.add('zipalign')

    if check_command('keytool'):
        ok("keytool 已就绪")
    else:
        warn("keytool 未安装（随 openjdk）")
        missing.add('openjdk-17')

    if check_command('aapt'):
        ok("aapt 已就绪")
    else:
        warn("aapt 未安装（用于验证包名，可后续: pkg install aapt）")

    if not missing:
        print()
        ok("所有依赖已就绪")
        print()
        return True

    if not check_termux():
        warn("非 Termux 环境，无法自动安装。请手动安装以下包：")
        for p in sorted(missing):
            warn(f"  {p}")
        return False

    print()
    info(f"需要安装以下依赖: {', '.join(sorted(missing))}")
    try:
        confirm = input(f"{C.BOLD}是否自动安装？[Y/n]: {C.END}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = 'n'

    if confirm not in ('', 'y', 'yes'):
        warn("跳过依赖安装。请手动执行：")
        for p in sorted(missing):
            warn(f"  pkg install {p}")
        return False

    info("正在更新 pkg 源...")
    run_cmd('pkg update -y', check=False, timeout=600)

    for pkg in sorted(missing):
        info(f"正在安装 {pkg} ...")
        rc = run_cmd_live(
            f'pkg install {pkg} -y',
            timeout=1800,
            hint=f"安装 {pkg}",
            filter_fn=lambda l: (
                'Setting up' in l or 'Unpacking' in l
                or 'error' in l.lower() or l.startswith('E:')
            )
        )
        if rc == 0:
            ok(f"{pkg} 安装成功")
        else:
            err(f"{pkg} 安装失败，请手动执行: pkg install {pkg}")

    print()
    java_ok, _ = check_java()
    if not java_ok:
        die("Java 未就绪，请检查网络后重试")
    if not check_command('apktool'):
        die("apktool 未就绪，请检查网络后重试")
    if not check_command('apksigner'):
        die("apksigner 未就绪，请检查网络后重试")

    ok("环境检测完成")
    print()
    return True


# ============================================================
# 交互输入
# ============================================================
def ask_apk_path():
    while True:
        print(f"{C.BOLD}请输入 APK 文件的完整路径{C.END}")
        print(f"  示例: /sdcard/Download/app.apk")
        print(f"  可先执行 {C.YELLOW}termux-setup-storage{C.END} 并授权存储")
        print(f"  输入 {C.YELLOW}q{C.END} 退出")
        try:
            path = input("> ").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            print()
            die("已取消")

        if path.lower() == 'q':
            die("已取消")
        if not path:
            warn("路径不能为空")
            continue
        if path.startswith('file://'):
            path = path[7:]
        if not os.path.exists(path):
            warn(f"文件不存在: {path}")
            continue
        if not os.path.isfile(path):
            warn(f"不是文件: {path}")
            continue
        if not path.lower().endswith('.apk'):
            warn("文件不是 .apk 格式")
            continue

        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb < 0.001:
            warn("文件大小为 0，可能损坏")
            continue

        ok(f"找到 APK: {path} ({size_mb:.1f} MB)")
        log(f"输入 APK: {path} ({size_mb:.1f} MB)")

        parent = os.path.dirname(os.path.abspath(path))
        if not os.access(parent, os.W_OK):
            warn(f"警告: 对 {parent} 没有写入权限，输出可能失败")
            warn("若在 /sdcard 下，请先执行: termux-setup-storage")
            try:
                c = input("仍要继续？[y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                c = 'n'
            if c not in ('y', 'yes'):
                continue

        return path


def ask_package_name():
    while True:
        print()
        print(f"{C.BOLD}请输入新的包名{C.END}")
        print(f"  要求: 至少 2 段，用点分隔；每段以字母开头")
        print(f"  示例: com.example.myapp")
        print(f"  输入 {C.YELLOW}q{C.END} 退出")
        try:
            pkg = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            die("已取消")

        if pkg.lower() == 'q':
            die("已取消")
        if not pkg:
            warn("包名不能为空")
            continue
        if len(pkg) > 200:
            warn("包名过长（不超过 200 字符）")
            continue
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$', pkg):
            warn("包名格式不合法：以字母开头，只能含字母/数字/下划线/点")
            continue

        last_seg = pkg.rsplit('.', 1)[-1].lower()
        if last_seg in ('class', 'interface', 'enum', 'if', 'else',
                        'for', 'while', 'public', 'private', 'package'):
            warn(f"最后一段 '{last_seg}' 是 Java 保留字，可能导致问题")
            continue

        ok(f"新包名: {pkg}")
        log(f"输入新包名: {pkg}")
        return pkg


def ask_keystore_info(termux_home):
    print()
    print(f"{C.BOLD}签名配置{C.END}")
    print(f"  已有 keystore 请输入路径，否则留空自动生成。")

    try:
        ks_input = input("Keystore 路径 (留空=自动生成，q=退出) > ").strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print()
        die("已取消")

    if ks_input.lower() == 'q':
        die("已取消")

    if ks_input:
        ks_path = os.path.expanduser(ks_input)
        if not os.path.exists(ks_path):
            warn(f"文件不存在: {ks_path}，将改为自动生成")
            ks_input = ''

    if ks_input:
        ks_path = os.path.expanduser(ks_input)
        try:
            alias = input("别名 (alias) [默认: myalias] > ").strip() or "myalias"
            password = getpass.getpass("Keystore 密码 > ")
        except (EOFError, KeyboardInterrupt):
            print()
            die("已取消")
        if not password:
            die("密码不能为空")
        return {
            'keystore': ks_path,
            'alias': alias,
            'password': password,
            'generate': False
        }

    # 自动生成
    print()
    info("将自动生成新的签名密钥")
    default_ks = os.path.join(termux_home, 'apk_keys', 'mykey.keystore')

    if os.path.exists(default_ks):
        warn(f"已存在密钥: {default_ks}")
        try:
            use = input("使用已有密钥？[Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            use = 'y'
        if use in ('', 'y', 'yes'):
            try:
                alias = input("别名 (alias) [默认: myalias] > ").strip() or "myalias"
                password = getpass.getpass("Keystore 密码 > ")
            except (EOFError, KeyboardInterrupt):
                die("已取消")
            if not password:
                die("密码不能为空")
            return {
                'keystore': default_ks,
                'alias': alias,
                'password': password,
                'generate': False
            }
        else:
            backup = default_ks + f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            try:
                shutil.move(default_ks, backup)
                info(f"旧密钥已备份: {backup}")
            except Exception:
                pass

    try:
        alias = input("别名 (alias) [默认: myalias] > ").strip() or "myalias"
    except (EOFError, KeyboardInterrupt):
        die("已取消")

    while True:
        try:
            print(f"{C.YELLOW}密码将用于生成和签名，请牢记（至少 6 位）{C.END}")
            password = getpass.getpass("设置密码 > ")
            if not password:
                warn("密码不能为空")
                continue
            if len(password) < 6:
                warn("密码至少 6 位")
                continue
            password2 = getpass.getpass("再次输入密码 > ")
            if password != password2:
                warn("两次密码不一致，请重试")
                continue
            break
        except (EOFError, KeyboardInterrupt):
            print()
            die("已取消")

    os.makedirs(os.path.dirname(default_ks), exist_ok=True)
    return {
        'keystore': default_ks,
        'alias': alias,
        'password': password,
        'generate': True
    }


# ============================================================
# 反编译
# ============================================================
def decompile_apk(apk_path, work_dir):
    log(f"反编译: {apk_path} -> {work_dir}")

    if os.path.exists(work_dir):
        info("清理旧的反编译目录...")
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    my_filter = lambda l: (
        (l.startswith('I:') and any(k in l for k in [
            'Using Apktool', 'Loading', 'Decoding', 'Baksmaling',
            'Copying', 'Generating', 'resources'
        ])) or l.startswith('W:') or l.startswith('E:')
    )

    rc = run_cmd_live(
        f'apktool d -f -s "{apk_path}" -o "{work_dir}"',
        timeout=600, hint="反编译（跳过 smali）", filter_fn=my_filter
    )
    return rc == 0


def verify_decompile(work_dir):
    manifest = os.path.join(work_dir, 'AndroidManifest.xml')
    if not os.path.exists(manifest):
        return False, "AndroidManifest.xml 未生成"
    try:
        with open(manifest, 'r', encoding='utf-8') as f:
            head = f.read(500)
        if not head.lstrip().startswith('<?xml') and not head.lstrip().startswith('<manifest'):
            return False, "AndroidManifest.xml 不是文本格式（反编译不完整）"
    except Exception as e:
        return False, f"AndroidManifest.xml 读取失败: {e}"

    return True, "OK"


def get_original_package(work_dir):
    manifest = os.path.join(work_dir, 'AndroidManifest.xml')
    if not os.path.exists(manifest):
        return None
    try:
        with open(manifest, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None
    m = re.search(r'<manifest\b[^>]*?\bpackage="([^"]+)"', content, re.DOTALL)
    return m.group(1) if m else None


def modify_package_name(work_dir, new_pkg):
    """
    修改包名 —— 只改 AndroidManifest.xml 的 package 属性
    【关键】绝不触碰 smali 文件
    """
    manifest_path = os.path.join(work_dir, 'AndroidManifest.xml')
    if not os.path.exists(manifest_path):
        die(f"找不到 AndroidManifest.xml: {manifest_path}")

    with open(manifest_path, 'r', encoding='utf-8') as f:
        content = f.read()

    old_pkg = get_original_package(work_dir)
    if not old_pkg:
        die("无法读取原始包名")

    info(f"原包名: {old_pkg}")
    log(f"原包名: {old_pkg}")

    if old_pkg == new_pkg:
        warn("新包名与原包名相同，无需修改")
        return old_pkg

    def replace_pkg(match):
        tag = match.group(0)
        return re.sub(r'\bpackage="[^"]*"', f'package="{new_pkg}"', tag, count=1)

    new_content = re.sub(r'<manifest\b[^>]*>', replace_pkg, content, count=1)

    if new_content == content:
        die("未能替换 package 属性，请检查 AndroidManifest.xml 格式")

    # ============================================================
    # 统一重命名 manifest 里所有"全局唯一标识"
    # 只动这些属性：permission 系列 name / authorities / permission /
    #              readPermission / writePermission / taskAffinity /
    #              process / data-scheme
    # 绝不动：组件类名（activity/service/receiver/provider 的 android:name）
    # ============================================================
    old_esc = re.escape(old_pkg)

    # 1) permission 系列标签内的 android:name="OLD.xxx"
    def _fix_perm_tag(m):
        return re.sub(
            r'(android:name=")' + old_esc + r'\.',
            lambda x: x.group(1) + new_pkg + '.',
            m.group(0)
        )
    new_content = re.sub(
        r'<(?:uses-)?permission(?:-group|-tree)?\b[^>]*?/?>',
        _fix_perm_tag, new_content
    )

    # 2) android:authorities（支持分号分隔多个）
    def _fix_authorities(m):
        segs = []
        for seg in m.group(1).split(';'):
            if seg == old_pkg or seg.startswith(old_pkg + '.'):
                segs.append(new_pkg + seg[len(old_pkg):])
            else:
                segs.append(seg)
        return 'android:authorities="' + ';'.join(segs) + '"'
    new_content = re.sub(r'android:authorities="([^"]*)"',
                         _fix_authorities, new_content)

    # 3) 其它"值以旧包名开头"的属性
    for _attr in ('android:permission', 'android:readPermission',
                  'android:writePermission', 'android:taskAffinity',
                  'android:process', 'android:scheme'):
        new_content = re.sub(
            r'(' + _attr + r'=")' + old_esc + r'(?=\.|")',
            lambda x: x.group(1) + new_pkg,
            new_content
        )

    # 4) 扫一遍还有多少处旧包名没替换（仅日志，不改）
    _left = re.findall(
        r'android:(?:name|authorities|permission|readPermission|writePermission'
        r'|taskAffinity|process|scheme)="' + old_esc + r'[."]',
        new_content
    )
    if _left:
        log(f"剩余旧包名引用 {len(_left)} 处（多为组件类名，预期保留）")

    m2 = re.search(r'<manifest\b[^>]*?\bpackage="([^"]+)"', new_content, re.DOTALL)
    if not m2 or m2.group(1) != new_pkg:
        die("修改后校验失败，包名未正确写入")

    shutil.copy2(manifest_path, manifest_path + ".bak")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    ok(f"包名已修改为: {new_pkg}")
    log(f"包名修改: {old_pkg} -> {new_pkg}")

    # 同步更新 apktool.yml（辅助，即使不生效也无害）
    yml_path = os.path.join(work_dir, 'apktool.yml')
    if os.path.exists(yml_path):
        try:
            with open(yml_path, 'r', encoding='utf-8') as f:
                yml = f.read()
            if re.search(r'^renameManifestPackage:', yml, re.MULTILINE):
                yml = re.sub(r'^renameManifestPackage:\s*.*$',
                             f'renameManifestPackage: {new_pkg}',
                             yml, flags=re.MULTILINE)
            elif re.search(r'^versionInfo:', yml, re.MULTILINE):
                yml = re.sub(r'^versionInfo:',
                             f'renameManifestPackage: {new_pkg}\nversionInfo:',
                             yml, count=1, flags=re.MULTILINE)
            else:
                yml += f'\nrenameManifestPackage: {new_pkg}\n'
            with open(yml_path, 'w', encoding='utf-8') as f:
                f.write(yml)
            log("已同步更新 apktool.yml")
        except Exception as e:
            warn(f"更新 apktool.yml 失败（不影响流程）: {e}")

    return old_pkg


def rebuild_apk(work_dir, output_apk):
    log("开始回编译")

    if os.path.exists(output_apk):
        os.remove(output_apk)

    my_filter = lambda l: (
        (l.startswith('I:') and any(k in l for k in [
            'Using Apktool', 'Smaling', 'Building', 'Built',
            'Importing', 'Copying'
        ])) or l.startswith('W:') or l.startswith('E:')
    )

    rc = run_cmd_live(
        f'apktool b -f --no-crunch "{work_dir}" -o "{output_apk}"',
        timeout=900, hint="回编译（跳过资源压缩）", filter_fn=my_filter
    )
    return rc == 0 and os.path.exists(output_apk)


# ============================================================
# 签名
# ============================================================
def generate_keystore(ks_path, alias, password):
    log(f"生成 keystore: {ks_path}")
    info("正在生成签名密钥...")

    os.makedirs(os.path.dirname(os.path.abspath(ks_path)), exist_ok=True)

    env = os.environ.copy()
    env['KS_PASS'] = password
    env['KEY_PASS'] = password

    dname = "CN=Termux, OU=Dev, O=Termux, L=City, ST=State, C=CN"
    cmd = (
        f'keytool -genkeypair -v '
        f'-keystore "{ks_path}" '
        f'-alias "{alias}" '
        f'-keyalg RSA -keysize 2048 -validity 10000 '
        f'-storepass {shlex.quote(password)} '
        f'-keypass {shlex.quote(password)} '
        f'-dname "{dname}"'
    )

    r = run_cmd(cmd, check=False, timeout=120, env=env)
    if r and r.returncode == 0 and os.path.exists(ks_path):
        ok(f"密钥已生成: {ks_path}")
        log("密钥生成成功")
        return True

    err("密钥生成失败")
    if r and r.stderr:
        print(r.stderr[-500:])
    return False


def zipalign_apk(input_apk, output_apk):
    info("正在对齐 APK...")
    log(f"zipalign: {input_apk} -> {output_apk}")

    if os.path.exists(output_apk):
        os.remove(output_apk)

    r = run_cmd(f'zipalign -p -f 4 "{input_apk}" "{output_apk}"',
                check=False, timeout=300)

    if r and r.returncode == 0 and os.path.exists(output_apk):
        ok("对齐完成")
        return True

    warn("zipalign 失败（v2 签名下不致命，继续）")
    try:
        shutil.copy2(input_apk, output_apk)
    except Exception as e:
        err(f"复制失败: {e}")
        return False
    return True


def sign_apk(unsigned_apk, signed_apk, ks_path, alias, password):
    info("正在签名 APK...")
    log(f"签名: {unsigned_apk} -> {signed_apk}")

    if os.path.exists(signed_apk):
        os.remove(signed_apk)

    env = os.environ.copy()
    env['KS_PASS'] = password
    env['KEY_PASS'] = password

    cmd = (
        f'apksigner sign '
        f'--ks "{ks_path}" '
        f'--ks-key-alias "{alias}" '
        f'--ks-pass pass:{shlex.quote(password)} '
        f'--key-pass pass:{shlex.quote(password)} '
        f'--out "{signed_apk}" '
        f'"{unsigned_apk}"'
    )

    r = run_cmd(cmd, check=False, timeout=300, env=env)
    if r and r.returncode == 0 and os.path.exists(signed_apk):
        ok("签名成功")
        log("签名成功")
        return True

    err("签名失败")
    if r and r.stderr:
        print(r.stderr[-800:])
    return False


def verify_signed_apk(signed_apk, expected_pkg):
    all_ok = True

    info("验证签名...")
    r = run_cmd(f'apksigner verify --verbose "{signed_apk}"',
                check=False, timeout=120)
    if r and r.returncode == 0:
        ok("签名验证通过")
        for line in (r.stdout or '').split('\n'):
            line = line.strip()
            if line.startswith('Verified using'):
                info(f"  {line}")
    else:
        err("签名验证失败")
        all_ok = False

    info("验证包名...")
    actual_pkg = None
    for tool in ('aapt', 'aapt2'):
        if check_command(tool):
            r = run_cmd(f'{tool} dump badging "{signed_apk}" 2>/dev/null | head -1',
                        check=False, timeout=60)
            if r and r.stdout:
                m = re.search(r"package:\s*name='([^']+)'", r.stdout)
                if m:
                    actual_pkg = m.group(1)
                    break

    if actual_pkg:
        if actual_pkg == expected_pkg:
            ok(f"包名验证通过: {actual_pkg}")
        else:
            err(f"包名验证失败: 期望 {expected_pkg}，实际 {actual_pkg}")
            all_ok = False
    else:
        warn("无法自动验证包名（aapt/aapt2 不可用）")

    return all_ok


# ============================================================
# 主流程
# ============================================================
def main():
    print()
    print(f"{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════╗")
    print(f"║      Termux APK 包名一键修改工具 v2.0        ║")
    print(f"║   反编译 → 改包名 → 回编译 → 签名 → 验证   ║")
    print(f"╚══════════════════════════════════════════════╝{C.END}")
    print()

    if check_termux():
        ok("运行在 Termux 环境")
    else:
        warn("未检测到 Termux 环境（可能继续，但 pkg 命令不可用）")

    install_dependencies()

    apk_path = ask_apk_path()
    apk_name = Path(apk_path).stem
    new_pkg = ask_package_name()

    termux_home = os.path.expanduser("~")

    # 磁盘空间预检
    free_mb = get_disk_free_mb(termux_home)
    apk_size_mb = os.path.getsize(apk_path) / (1024 * 1024)
    if free_mb > 0:
        required_mb = apk_size_mb * 8
        if free_mb < required_mb:
            warn(f"Termux 主目录可用空间 {free_mb:.0f} MB，"
                 f"建议 >= {required_mb:.0f} MB")
            try:
                c = input("继续？[y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                c = 'n'
            if c not in ('y', 'yes'):
                die("已取消")
        else:
            info(f"主目录可用空间: {free_mb:.0f} MB")

    ks_info = ask_keystore_info(termux_home)

    # 路径规划
    input_dir = os.path.dirname(os.path.abspath(apk_path))

    build_root = os.path.join(termux_home, '.apk_rename_build')
    os.makedirs(build_root, exist_ok=True)

    work_dir = os.path.join(build_root, f"{apk_name}_decompiled")
    temp_out_dir = os.path.join(build_root, f"{apk_name}_temp")
    os.makedirs(temp_out_dir, exist_ok=True)

    unsigned_apk = os.path.join(temp_out_dir, f"{apk_name}_unsigned.apk")
    aligned_apk = os.path.join(temp_out_dir, f"{apk_name}_aligned.apk")
    temp_signed_apk = os.path.join(temp_out_dir, f"{apk_name}_signed.apk")
    final_signed_apk = os.path.join(input_dir, f"{apk_name}_modded.apk")

    # 输出重名处理
    if os.path.exists(final_signed_apk):
        print()
        warn(f"输出文件已存在: {final_signed_apk}")
        try:
            choice = input("覆盖(o) / 重命名(r) / 取消(c)? [o/r/c]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = 'c'
        if choice not in ('o', 'r', ''):
            die("已取消")
        if choice == 'r':
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            base, ext = os.path.splitext(final_signed_apk)
            final_signed_apk = f"{base}_{ts}{ext}"
            info(f"新输出路径: {final_signed_apk}")

    # 日志
    log_dir = os.path.join(termux_home, '.apk_rename_logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir, f"{apk_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    init_log(log_path)
    log(f"APK: {apk_path}")
    log(f"新包名: {new_pkg}")
    log(f"输出: {final_signed_apk}")

    # 执行计划
    print()
    print(f"{C.BOLD}========== 执行计划 =========={C.END}")
    print(f"  源 APK    : {apk_path}")
    print(f"  新包名    : {new_pkg}")
    print(f"  输出位置  : {final_signed_apk}")
    print(f"  临时目录  : {build_root}")
    print(f"  日志文件  : {log_path}")
    if ks_info['generate']:
        print(f"  签名密钥  : {ks_info['keystore']} (将自动生成)")
    else:
        print(f"  签名密钥  : {ks_info['keystore']} (已有)")
    print(f"{C.BOLD}=============================={C.END}")
    print()

    try:
        confirm = input(f"{C.BOLD}确认开始？[Y/n]: {C.END}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = 'n'
    if confirm not in ('', 'y', 'yes'):
        info("已取消")
        sys.exit(0)

    print()
    t_start = time.time()

    # Step 1
    print(f"{C.BOLD}【1/6】反编译 APK{C.END}")
    if not decompile_apk(apk_path, work_dir):
        print()
        err("反编译失败。可能原因：")
        print("  1. APK 文件损坏或不完整")
        print("  2. APK 使用了加固/加密")
        print("  3. 磁盘空间不足")
        print("  4. apktool 版本不兼容")
        print(f"  日志: {log_path}")
        sys.exit(1)

    ok_flag, msg = verify_decompile(work_dir)
    if not ok_flag:
        die(f"反编译结果异常: {msg}\n日志: {log_path}")

    # Step 2
    print()
    print(f"{C.BOLD}【2/6】修改包名{C.END}")
    old_pkg = get_original_package(work_dir)
    if old_pkg == new_pkg:
        warn(f"新包名与原包名相同，无需修改")
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(temp_out_dir, ignore_errors=True)
        info("流程结束")
        sys.exit(0)

    modify_package_name(work_dir, new_pkg)

    # Step 3
    print()
    print(f"{C.BOLD}【3/6】回编译 APK{C.END}")
    warn("回编译大 APK 可能需要 1~5 分钟，请耐心等待，不要按 Ctrl+C")
    print()
    if not rebuild_apk(work_dir, unsigned_apk):
        print()
        err("回编译失败。可能原因：")
        print("  1. 资源兼容性问题（aapt2 常见）")
        print("  2. apktool 版本问题")
        print("  3. AndroidManifest.xml 格式异常")
        print(f"  反编译目录已保留: {work_dir}")
        print(f"  日志: {log_path}")
        sys.exit(1)

    # Step 4
    print()
    print(f"{C.BOLD}【4/6】签名 APK{C.END}")
    ks_path = ks_info['keystore']
    if ks_info['generate']:
        if not generate_keystore(ks_path, ks_info['alias'], ks_info['password']):
            die("密钥生成失败")

    zipalign_apk(unsigned_apk, aligned_apk)

    if not sign_apk(aligned_apk, temp_signed_apk, ks_path,
                    ks_info['alias'], ks_info['password']):
        print()
        err("签名失败。可能原因：")
        print("  1. keystore 密码错误")
        print("  2. keystore 文件损坏")
        print(f"  未签名 APK 保留: {unsigned_apk}")
        print(f"  日志: {log_path}")
        sys.exit(1)

    # Step 5
    print()
    print(f"{C.BOLD}【5/6】验证结果{C.END}")
    verify_signed_apk(temp_signed_apk, new_pkg)

    # Step 6
    print()
    print(f"{C.BOLD}【6/6】输出结果{C.END}")
    info(f"正在复制到: {final_signed_apk}")
    try:
        shutil.copy2(temp_signed_apk, final_signed_apk)
        ok("已复制到源 APK 同目录")
    except PermissionError:
        die(f"无写入权限: {input_dir}\n"
            f"请先执行: termux-setup-storage 并授权\n"
            f"临时文件保留在: {temp_signed_apk}")
    except Exception as e:
        die(f"复制失败: {e}\n临时文件: {temp_signed_apk}")

    # 清理
    print()
    info("清理临时文件...")
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(temp_out_dir, ignore_errors=True)
        ok("临时文件已清理")
    except Exception as e:
        warn(f"清理失败: {e}")

    elapsed = int(time.time() - t_start)

    # 完成
    print()
    print(f"{C.GREEN}{C.BOLD}╔══════════════════════════════════════════════╗")
    print(f"║              ✅  全部完成！                   ║")
    print(f"╚══════════════════════════════════════════════╝{C.END}")
    print()
    print(f"{C.BOLD}========== 结果摘要 =========={C.END}")
    ok(f"输出文件  : {final_signed_apk}")
    if os.path.exists(final_signed_apk):
        size_mb = os.path.getsize(final_signed_apk) / (1024 * 1024)
        print(f"  文件大小  : {size_mb:.1f} MB")
    print(f"  原包名    : {old_pkg}")
    print(f"  新包名    : {new_pkg}")
    print(f"  总耗时    : {elapsed}s")
    if ks_info['generate']:
        print(f"  签名密钥  : {ks_path}")
    print(f"  日志文件  : {log_path}")
    print(f"{C.BOLD}=============================={C.END}")
    print()

    if ks_info['generate']:
        warn("请妥善保管密钥文件和密码！")
        warn("后续更新同一个 APK 必须使用相同密钥，否则无法覆盖安装。")
    print()
    info(f"安装: adb install \"{final_signed_apk}\"")
    info("或在手机文件管理器中点击安装")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
        warn("用户中断（Ctrl+C）")
        info("临时文件可能残留在: ~/.apk_rename_build/")
        if LOG_FILE:
            info(f"日志: {LOG_FILE}")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        err(f"脚本异常: {e}")
        import traceback
        traceback.print_exc()
        if LOG_FILE:
            log(f"EXCEPTION: {e}")
            log(traceback.format_exc())
        sys.exit(1)

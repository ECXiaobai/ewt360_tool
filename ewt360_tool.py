"""ewt360 刷课单文件独立版（零依赖，仅需 requests + Python 标准库）。

基于 APP 端协议（bfe/monitor/app/collect/batch + Android 指纹）：
- 服务器对 APP 端(platform=2)校验宽松，每轮 120s 步进 + 间隔 60s，每轮 +120s 进度
- 实测达标（2026-08-07）：10 分钟课时约 5 分钟刷完，每轮 playTime 精确 +120000ms

用法:
    python ewt360_tool.py --list
    python ewt360_tool.py --all --go
    python ewt360_tool.py --all --go --biz 1014
    python ewt360_tool.py 0 1 2 --go

登录优先级: --token <token> > config.yml ewt360.access_token > cred.txt > 交互输入
"""

import hashlib
import hmac
import math
import random
import sys
import time
from pathlib import Path

import requests

# ==================== 配置 ====================
GATEWAY = "https://gateway.ewt360.com"
BFE = "https://bfe.ewt360.com"
REPORT_URL = f"{GATEWAY}/api/homeworkprod/homework/student/reportVideoPoint"
REPORT_KEY = "4dcc69ed56d6"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/105.1.13.2 Safari/543.56")

# ==================== 登录 ====================
def load_cred() -> tuple:
    """读 cred.txt (第一行账号, 第二行密码)；不存在返回 None"""
    p = Path(__file__).resolve().parent / "cred.txt"
    if not p.exists():
        return None
    lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    return (lines[0], lines[1]) if len(lines) >= 2 else None


def login(session, token_arg: str = "") -> str:
    """返回 token。优先级: 参数 > config.yml > cred.txt > 交互"""
    if token_arg:
        return token_arg.strip()
    # config.yml
    try:
        import yaml
        p = Path(__file__).resolve().parent / "config.yml"
        if p.exists():
            conf = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            ewt = conf.get("ewt360", {}) or {}
            if ewt.get("access_token"):
                return str(ewt["access_token"]).strip()
            acc, pwd = ewt.get("account", ""), ewt.get("password", "")
            if acc and pwd:
                return login_by_account(session, acc, pwd)
    except Exception:
        pass
    # cred.txt
    cred = load_cred()
    if cred:
        return login_by_account(session, cred[0], cred[1])
    # 交互
    print("未配置登录方式。")
    print("  方式一: 粘贴 token")
    print("  方式二: 账号 + 密码 (AES 加密自动登录)")
    choice = input("请选择登录方式 (1=token, 2=账密, 回车=账密): ").strip()
    if choice == "1":
        tok = input("请输入 token (浏览器登录 ewt360 后从 Network 复制): ").strip()
        if tok:
            return tok
        sys.exit("未提供 token")
    # 账密登录
    account = input("请输入账号 (手机号/用户名): ").strip()
    try:
        import getpass
        password = getpass.getpass("请输入密码 (输入不显示): ").strip()
    except Exception:
        password = input("请输入密码: ").strip()
    if not account or not password:
        sys.exit("账号或密码为空")
    print("正在账密登录...")
    return login_by_account(session, account, password)


def now_ms() -> int:
    return int(time.time() * 1000)


def encrypt_password(password: str) -> str:
    """AES-256-CBC 加密密码 (key=2017110912453698*2, iv=2017110912453698, Pkcs7, hex 大写)"""
    from Crypto.Cipher import AES
    key = b"20171109124536982017110912453698"
    iv = b"2017110912453698"
    text = password.encode("utf-8")
    pad = 16 - len(text) % 16
    text = text + bytes([pad]) * pad
    return AES.new(key, AES.MODE_CBC, iv=iv).encrypt(text).hex().upper()


def sign_ts(ts: int) -> str:
    """登录请求头 sign = MD5(ts + 'bdc739ff2dcf') 大写"""
    return hashlib.md5(f"{ts}bdc739ff2dcf".encode()).hexdigest().upper()


def login_by_account(session, account: str, password: str) -> str:
    ts = now_ms()
    headers = {
        "accept": "application/json",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://web.ewt360.com",
        "referer": "https://web.ewt360.com/",
        "platform": "1",
        "secretid": "2",
        "sign": sign_ts(ts),
        "timestamp": str(ts),
        "user-agent": UA,
    }
    body = {
        "autoLogin": "true",
        "password": encrypt_password(password),
        "platform": 1,
        "userName": account,
        "webVersion": "pc_20250101",
    }
    r = session.post(f"{GATEWAY}/api/authcenter/v2/oauth/login/account",
                     json=body, headers=headers, timeout=15)
    data = r.json()
    if data.get("code") != "200":
        sys.exit(f"登录失败: {data}")
    return data["data"]["token"]


# ==================== 接口 ====================
def req(session, method, url, token, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.setdefault("token", token)
    headers.setdefault("user-agent", UA)
    r = session.request(method, url, headers=headers, timeout=15, **kwargs)
    return r.json()


def get_user_info(session, token):
    d = req(session, "GET", f"{GATEWAY}/api/eteacherproduct/school/getSchoolUserInfo", token)
    if d.get("code") != "200":
        sys.exit(f"获取用户信息失败: {d}")
    return str(d["data"]["schoolId"]), str(d["data"]["userId"])


def get_homework_list(session, token, school_id):
    d = req(session, "POST", f"{GATEWAY}/api/homeworkprod/homework/student/getStudentHomeworkInfo",
             token, json={
                 "schoolId": school_id, "subject": None, "type": None,
                 "status": 2, "pageIndex": 1, "pageSize": 20, "notClassSetting": 0,
             })
    if d.get("code") != "200":
        sys.exit(f"获取作业列表失败: {d}")
    return d.get("data") or []


def get_day_ids(session, token, homework_id, scene_id, school_id):
    d = req(session, "POST", f"{GATEWAY}/api/homeworkprod/homework/student/holiday/getHomeworkDistribution?sceneId={scene_id}",
             token, json={
                 "homeworkIds": [homework_id], "isSelfTask": "false",
                 "userOptionTaskId": "null", "schoolId": school_id,
                 "sceneId": str(scene_id),
             })
    if d.get("code") != "200":
        return []
    return [x["dayId"][0] for x in (d["data"].get("days") or []) if x.get("dayId")]


def get_tasks(session, token, homework_id, day_id, school_id):
    d = req(session, "POST", f"{GATEWAY}/api/homeworkprod/student/homework/task/pageHomeworkTasks",
             token, json={
                 "schoolId": school_id, "homeworkId": int(homework_id),
                 "mustLearnSubjectList": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                 "queryMustLearn": 1, "dayId": day_id,
                 "pageIndex": 1, "pageSize": 30,
             })
    if d.get("code") != "200":
        return []
    return (d.get("data") or {}).get("data") or []


def collect_lessons(session, token, school_id) -> list:
    """收集全部任务 (视频 ct=1 / 试卷 ct=2 / FM ct=3 / 板报 ct=5 等)。"""
    from urllib.parse import parse_qs
    lessons = []
    for hw in get_homework_list(session, token, school_id):
        hw_id = hw.get("homeworkId")
        scene_id = hw.get("sceneId")
        if not hw_id:
            continue
        for day_id in get_day_ids(session, token, hw_id, scene_id, school_id):
            for t in get_tasks(session, token, hw_id, day_id, school_id):
                ct = t.get("contentType")
                if ct not in (1, 2, 3, 5, None):
                    continue
                # 试卷 (ct=2): 从 contentUrl 解析 paperId/bizCode (answerprod 交卷用)
                paper_id = biz_code = ""
                url = str(t.get("contentUrl") or "")
                if "?" in url:
                    q = parse_qs(url.split("?")[1])
                    paper_id = q.get("paperId", [""])[0]
                    biz_code = q.get("bizCode", [""])[0]
                lessons.append({
                    "title": t.get("title") or hw.get("title", ""),
                    "lesson_id": str(t.get("contentId", "") or ""),
                    "course_id": str(t.get("parentContentId", "") or ""),
                    "content_type": ct if ct is not None else 1,
                    "duration": float(t.get("duration", 0) or 0),
                    "ratio": round(float(t.get("ratio", 0) or 0), 7),
                    "homework_id": int(hw_id),
                    "paper_id": paper_id,
                    "biz_code": biz_code,
                    # bizcode 是作业/任务特定的(作者: 需从浏览器抓包提取)!
                    # 任务数据可能自带 bizCode/videoBizCode/bizcode 字段, 优先取任务级
                    "bizcode": str(t.get("bizCode") or t.get("videoBizCode")
                                   or t.get("bizcode") or t.get("extBizNo") or ""),
                })
    return lessons


def finish_paper_blank(session, token, homework_id, paper_id, biz_code) -> bool:
    """白卷交卷 (answerprod, 实测有效): GET report 拿 reportId → POST submitpaper 交卷。"""
    d = req(session, "GET", f"{GATEWAY}/api/answerprod/web/answer/report", token,
            params={"paperId": paper_id, "platform": "1", "bizCode": biz_code, "token": token})
    if not d or d.get("code") != "200":
        return False
    report_id = d["data"]["reportId"]
    r = req(session, "POST", f"{GATEWAY}/api/answerprod/web/answer/submitpaper", token, json={
        "paperId": paper_id, "reportId": report_id, "bizCode": biz_code,
        "platform": "1", "totalSeconds": 600, "homeworkId": str(homework_id),
    })
    return bool(r and r.get("code") == "200")


def update_mission(session, token, school_id, content_id, content_type, percent=1) -> dict:
    """任务型直写完成度 (HAR 实锤 teacher.ewt360.com11.har):
    POST /api/homeworkprod/homework/student/updateMission
    BODY: {"schoolId":..,"contentId":"..","contentType":3|5,"percent":1}
    FM(3)/板报(5) 等任务型不走 playTime 心跳, 一次调用直接写 100%!
    """
    return req(session, "POST", f"{GATEWAY}/api/homeworkprod/homework/student/updateMission",
               token, json={
                   "schoolId": school_id,
                   "contentId": str(content_id),
                   "contentType": content_type,
                   "percent": percent,
               })


def get_task_info(session, token, school_id, homework_id, lesson_id):
    d = req(session, "POST", f"{GATEWAY}/api/homeworkprod/homework/student/getUserHomeworkLessonTaskInfo",
             token, json={
                 "schoolId": school_id, "homeworkId": int(homework_id),
                 "lessonId": int(lesson_id), "contentType": 1,
             })
    if d.get("code") != "200":
        return {}
    return d.get("data") or {}


def get_player_config(session, token):
    d = req(session, "GET", f"{GATEWAY}/api/videoplayerprod/videoplayer/getPlayerGlobalConf",
             token, params={"videoBizCode": "1001", "sdkVersion": "3.0.37", "_": now_ms()})
    if d.get("code") != "200":
        sys.exit(f"获取播放器配置失败: {d}")
    gi = d["data"]["globalInfo"]
    return gi["secret"], gi["sessionId"]


# ==================== APP 端协议 ====================
def app_signature(secret, action, duration, media_time, mstid, timestamp_ms):
    raw = (f"action={action}&duration={duration}&mediaTime={media_time}"
           f"&mstid={mstid}&platform=2&signatureMethod=HMAC-SHA1"
           f"&signatureVersion=1.0&timestamp={timestamp_ms}&version=2022-08-02")
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha1).hexdigest()


def build_common_package(user_id, token, school_id):
    return {
        "os": "Android", "appBrand": "android",
        "schoolProvinceCode": "320000", "memberProvinceCode": "320000",
        "userid": str(user_id), "resolution": "1080*2306", "platform": "2",
        "appOnline": "1", "osVersion": "10",
        "appDeviceModel": "android", "appDevId": "0f99d6c0-693e-3f13-abef-60f6af4d9218",
        "schoolId": str(school_id), "sdkVersion": "2.0.95-test-rc21",
        "appCarrier": "N/A", "appAccess": "NETWORK_MOBILE",
        "mstid": token, "appLanguage": "zh",
    }


def app_bfe_report(session, token, session_id, user_id, school_id, lesson_id, bizcode,
                   action, event_type, stay_ms, media_ms, point_time, begin_ts,
                   point_num, secret):
    timestamp_ms = now_ms()
    signature = app_signature(secret, action, stay_ms, media_ms, token, timestamp_ms)
    url = (f"{BFE}/monitor/app/collect/batch"
           f"?TrLessonId={lesson_id}&TrVideoBizCode={bizcode}&TrUuId=12341234"
           f"&TrFallback=0&TrUserId={user_id}&token={token}")
    headers = {
        "token": token, "x-bfe-session-id": session_id,
        "Content-Type": "application/json; charset=UTF-8", "Host": "bfe.ewt360.com",
    }
    body = {
        "CommonPackage": build_common_package(user_id, token, school_id),
        "EventPackage": [{
            "log_id": "12341234-1234-1234-1234-123412341234",
            "course_id": lesson_id, "appVersion": "11.11.11",
            "point_time": point_time, "point_time_id": 0, "begin_time": begin_ts,
            "lesson_id": lesson_id, "speed": 2.0, "appChannel": "android",
            "isonline": "1", "quality": "高清", "video_type": 1,
            "point_num": point_num, "event_type": event_type,
            "report_time": timestamp_ms, "media_time": media_ms,
            "action": action, "stay_time": stay_ms,
            "video_bizcode": bizcode, "status": 1,
        }],
        "signature": signature, "sn": "moses_ewt_video_detail_2026", "_": timestamp_ms,
    }
    r = session.post(url, json=body, headers=headers, timeout=15)
    return r.status_code, (r.text or "")[:150]


def report_video_point(session, token, homework_id, lesson_id):
    ts = now_ms()
    headers = {
        "Content-Type": "application/json", "token": token,
        "timestamp": str(ts),
        "sign": hashlib.md5(f"{ts}{REPORT_KEY}".encode()).hexdigest(),
    }
    body = {"homeworkId": homework_id, "lessonId": str(lesson_id),
            "type": 1, "platform": 2, "seriousCheckResult": 2}
    try:
        r = session.post(REPORT_URL, json=body, headers=headers, timeout=15)
        print(f"      ReportPoint -> Code {r.status_code} | {r.text[:100]}")
    except Exception as e:
        print(f"      [ERROR] 监测上报异常: {e}")


# ==================== 单课程刷课 ====================
def process_lesson(session, token, lesson, school_id, user_id, secret, session_id, bizcode):
    """APP 端刷课单个课时: 每轮 120s + 间隔 30s, 输出只显示课程名+进度"""
    name = lesson["title"][:30]
    # bizcode 优先取任务级(作业特定), 否则用传入的全局值
    task_biz = (lesson.get("bizcode") or "").strip()
    if task_biz:
        bizcode = task_biz
    info = get_task_info(session, token, school_id, lesson["homework_id"], lesson["lesson_id"])
    play_time = int(info.get("playTime") or 0)
    finish_time = int(info.get("finishPlayTime") or 0)
    if play_time >= finish_time:
        print(f"[{name}] ✅ 100% (已完成)")
        return True

    point_num = max(1, round(lesson["duration"] / 60))
    # 实测最快安全节奏 (2026-08-07): HEARTBEAT=120s 硬上限; 距上次成功心跳 ≥60s 才接受!
    # 30s 连续被限流(轮2距31s失败), 真实稳定节奏 = 120s 上报 + 60s 等待
    HEARTBEAT = 120000
    INTERVAL = 60000
    remaining = finish_time - play_time
    rounds = max(1, math.ceil(remaining / HEARTBEAT))
    begin_ts = now_ms()
    last_play = play_time

    def _show():
        pct = min(100, last_play * 100 // max(finish_time, 1))
        print(f"\r  [{name}] {pct}%", end="", flush=True)

    _show()
    for i in range(rounds):
        is_first = (i == 0)
        is_last = (i == rounds - 1)
        if is_first and is_last:
            action, etype = 4, "video_oper"
        elif is_first:
            action, etype = 2, "video_oper"
        elif is_last:
            action, etype = 4, "video"
        else:
            action, etype = 1, "video"

        code, text = app_bfe_report(session, token, session_id, user_id, school_id,
                                    lesson["lesson_id"], bizcode, action, etype,
                                    HEARTBEAT, HEARTBEAT, HEARTBEAT, begin_ts,
                                    point_num, secret)
        if code != 200:
            print(f"\n      [WARN] 心跳被拒 code={code} {text[:100]}")
        if is_last:
            report_video_point(session, token, lesson["homework_id"], lesson["lesson_id"])

        time.sleep(1)
        info_n = get_task_info(session, token, school_id, lesson["homework_id"], lesson["lesson_id"])
        cur = int(info_n.get("playTime") or 0)
        last_play = max(last_play, cur)
        _show()
        if cur >= finish_time:
            print(" ✅ 100%")
            return True

        if not is_last:
            delay = INTERVAL + random.randint(-200, 200)
            time.sleep(delay / 1000.0)

    info2 = get_task_info(session, token, school_id, lesson["homework_id"], lesson["lesson_id"])
    ok = int(info2.get("playTime") or 0) >= finish_time
    _show()
    print(" ✅ 100%" if ok else " ❌")
    return ok


# ==================== 主流程 ====================
def main():
    token_arg = ""
    if "--token" in sys.argv:
        token_arg = sys.argv[sys.argv.index("--token") + 1]
    LIST = "--list" in sys.argv
    ALL = "--all" in sys.argv
    GO = "--go" in sys.argv
    BIZ = "1014"
    if "--biz" in sys.argv:
        _i = sys.argv.index("--biz")
        BIZ = sys.argv[_i + 1] if _i + 1 < len(sys.argv) else "1014"
    IDXS = [int(a) for a in sys.argv[1:] if a.isdigit()]

    session = requests.Session()
    token = login(session, token_arg)
    school_id, user_id = get_user_info(session, token)
    print(f"登录成功 schoolId={school_id} userId={user_id}")

    lessons = collect_lessons(session, token, school_id)
    if not lessons:
        print("没有视频任务")
        return
    print(f"共 {len(lessons)} 个视频任务")

    if LIST:
        for i, l in enumerate(lessons):
            mark = "✅" if l["ratio"] >= 1.0 else "❌"
            print(f"  [{i}] {mark} {l['title'][:32]} | hw={l['homework_id']} lesson={l['lesson_id']} | {l['ratio']:.0%}")
        return

    # 选择任务
    if IDXS:
        picked = [lessons[i] for i in IDXS if i < len(lessons)]
    elif ALL:
        picked = [l for l in lessons if l["ratio"] < 1.0]
    else:
        print("\n待刷任务：")
        for i, l in enumerate(lessons):
            mark = "✅" if l["ratio"] >= 1.0 else "❌"
            print(f"  [{i}] {mark} {l['title'][:32]} | {l['ratio']:.0%}")
        raw = input("\n选择序号(逗号分隔, a=全部未达标, 回车=第一个): ").strip()
        if raw.lower() == "a":
            picked = [l for l in lessons if l["ratio"] < 1.0]
        elif raw:
            picked = [lessons[int(x)] for x in raw.replace("，", ",").split(",") if x.strip().isdigit()]
        else:
            picked = [next((l for l in lessons if l["ratio"] < 1.0), lessons[0])]

    if not picked:
        print("未选择任务")
        return

    secret, session_id = get_player_config(session, token)

    ok_cnt = fail_cnt = 0
    for seq, lesson in enumerate(picked, 1):
        try:
            ct = lesson.get("content_type")
            name = lesson["title"][:30]
            # 试卷 (ct=2): 白卷交卷, 直接完成任务
            if ct == 2:
                ok = finish_paper_blank(session, token, lesson["homework_id"],
                                        lesson.get("paper_id", ""), lesson.get("biz_code", ""))
                print(f"  [{name}] {'✅ 白卷交卷' if ok else '❌ 交卷失败'}")
            # 任务型 (FM=3 / 板报=5): updateMission 一次直写 100%, 不走心跳
            elif ct in (3, 5):
                resp = update_mission(session, token, school_id,
                                      lesson["lesson_id"], ct, percent=1)
                ok = bool(resp and resp.get("success"))
                print(f"  [{name}] {'✅ 100%' if ok else '❌ ' + str(resp.get('code'))}")
            else:
                ok = process_lesson(session, token, lesson, school_id, user_id,
                                    secret, session_id, BIZ)
        except Exception:
            ok = False
        if ok:
            ok_cnt += 1
        else:
            fail_cnt += 1
    print(f"\n全部处理完成: 成功 {ok_cnt} / 失败 {fail_cnt}")


if __name__ == "__main__":
    main()

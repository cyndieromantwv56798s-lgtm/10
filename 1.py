#!/usr/bin/env python3
"""
proxy_checker_live_print.py
- Input: proxy.txt (one per line: host:port or user:pass@host:port). All SOCKS5.
- Output:
    - proxy_results.txt  (detailed lines)
    - good_proxies.txt   (only proxies with status OK) — appended live
- Behavior: khi proxy sống (OK) sẽ in ngay ra màn hình và append vào good_proxies.txt
- Requires: pip install requests[socks]
"""

import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus
from threading import Lock

INPUT_FILE = "proxy.txt"
OUTPUT_RESULTS = "proxy_results.txt"
OUTPUT_GOOD = "good_proxies.txt"
TEST_IP_URL = "https://api.myip.com"
TEST_HEADERS_URL = "https://httpbin.org/headers"
TIMEOUT = 8
MAX_WORKERS = 40

file_lock = Lock()

def normalize_proxy(line: str) -> str:
    s = line.strip()
    if not s:
        return ""
    if s.startswith("socks5://") or s.startswith("socks5h://"):
        return s
    if "@" in s:
        auth, addr = s.split("@", 1)
        if ":" in auth:
            u, p = auth.split(":", 1)
            return f"socks5://{quote_plus(u)}:{quote_plus(p)}@{addr}"
        else:
            return f"socks5://{quote_plus(auth)}@{addr}"
    return f"socks5://{s}"

def get_own_ip() -> str:
    try:
        r = requests.get(TEST_IP_URL, timeout=TIMEOUT)
        j = r.json()
        return j.get("ip", "") if isinstance(j, dict) else str(j)
    except Exception:
        return ""

def check_single_proxy(line: str, real_ip: str) -> dict:
    line = line.strip()
    out = {
        "proxy": line,
        "status": "DEAD",
        "anonymity": "UNKNOWN",
        "public_ip": "",
        "latency_ms": "",
        "info": ""
    }
    if not line or line.startswith("#"):
        out["info"] = "empty/comment"
        return out

    proxy_url = normalize_proxy(line)
    proxies = {"http": proxy_url, "https": proxy_url}

    # Measure latency + get public IP via proxy
    t0 = time.time()
    try:
        r = requests.get(TEST_IP_URL, proxies=proxies, timeout=TIMEOUT)
        latency = (time.time() - t0) * 1000.0
        out["latency_ms"] = f"{latency:.0f}"
        if 200 <= r.status_code < 400:
            try:
                j = r.json()
                ip = j.get("ip", "") if isinstance(j, dict) else ""
            except Exception:
                ip = r.text.strip()
            out["public_ip"] = ip
            out["status"] = "OK"
        else:
            out["info"] = f"status_code={r.status_code}"
            return out
    except Exception as e:
        out["info"] = f"connect_error:{repr(e)}"
        return out

    # If public_ip missing -> unknown
    if not out["public_ip"]:
        out["anonymity"] = "UNKNOWN"
        out["info"] = "no_public_ip"
        return out

    # If public IP equals real IP -> transparent
    if real_ip and out["public_ip"] == real_ip:
        out["anonymity"] = "TRANSPARENT"
        out["info"] = f"public_ip==real_ip({real_ip})"
        return out

    # Else public IP differs, check headers to detect proxy headers
    try:
        r2 = requests.get(TEST_HEADERS_URL, proxies=proxies, timeout=TIMEOUT)
        if 200 <= r2.status_code < 400:
            headers_json = r2.json().get("headers", {})
            headers_lower = {k.lower(): v for k, v in headers_json.items()}
            present = [k for k in ("via","x-forwarded-for","forwarded","client-ip") if k in headers_lower]
            # If X-Forwarded-For contains real ip -> transparent
            xff = headers_lower.get("x-forwarded-for", "")
            if real_ip and real_ip in xff:
                out["anonymity"] = "TRANSPARENT"
                out["info"] = f"X-Forwarded-For contains real IP ({real_ip})"
                return out
            if present:
                out["anonymity"] = "ANONYMOUS"
                out["info"] = "proxy_headers_present: " + ",".join(present)
                return out
            else:
                out["anonymity"] = "ELITE"
                out["info"] = "no proxy headers seen"
                return out
        else:
            out["anonymity"] = "UNKNOWN"
            out["info"] = f"headers_status={r2.status_code}"
            return out
    except Exception as e:
        out["anonymity"] = "UNKNOWN"
        out["info"] = f"headers_check_error:{repr(e)}"
        return out

def load_proxies(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip()]

def main():
    print("Lấy IP thật...")
    real_ip = get_own_ip()
    if real_ip:
        print("IP thật:", real_ip)
    else:
        print("Không lấy được IP thật. Classification có thể thiếu chính xác.")

    proxies = load_proxies(INPUT_FILE)
    print(f"Đang kiểm tra {len(proxies)} proxies (SOCKS5) ...\n")

    results = []
    # Ensure good_proxies file exists (and clear previous if desired)
    # If you prefer to append to previous run, comment out the next two lines.
    open(OUTPUT_GOOD, "w", encoding="utf-8").close()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(check_single_proxy, p, real_ip): p for p in proxies}
        for fut in as_completed(futs):
            res = fut.result()
            results.append(res)

            # Print every result line (status)
            line = f"[{res['status']}] {res['proxy']} -> {res['anonymity']}  {res['public_ip']}  {res['latency_ms']}ms  {res['info']}"
            print(line)

            # If proxy is OK, also print a highlighted live message and append to good_proxies.txt
            if res["status"] == "OK":
                live_msg = f"--> LIVE: {res['proxy']}  ({res['anonymity']}, {res['public_ip']}, {res['latency_ms']}ms)"
                print(live_msg)
                # thread-safe append
                with file_lock:
                    with open(OUTPUT_GOOD, "a", encoding="utf-8") as g:
                        g.write(res["proxy"] + "\n")

    # After all done, write full results file
    with open(OUTPUT_RESULTS, "w", encoding="utf-8") as outf:
        for r in results:
            out_line = f"[{r['status']}] {r['proxy']} -> {r['anonymity']} {r['public_ip']} {r['latency_ms']}ms {r['info']}"
            outf.write(out_line + "\n")

    print(f"\nHoàn tất. Kết quả lưu: {OUTPUT_RESULTS}, {OUTPUT_GOOD}")

if __name__ == "__main__":
    main()

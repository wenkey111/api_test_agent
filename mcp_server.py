from fastmcp import FastMCP
import os
import re
import json
import shutil
import subprocess

mcp = FastMCP("Test Automation Tools")


def _validate_path(p: str) -> bool:
    """路径安全校验：拦截目录穿越与绝对路径（URL 协议除外）。"""
    if ".." in p or p.startswith(("/", "\\")):
        return False
    if ":" in p and not p.startswith(("http://", "https://")):
        return False
    return True


@mcp.tool()
def fetch_api_spec(source: str) -> str:
    """获取最新 Swagger/OpenAPI 接口契约。source 支持 http(s) URL 或本地 .json/.yaml 路径。"""
    try:
        if source.startswith(("http://", "https://")):
            import requests
            r = requests.get(source, timeout=15)
            r.raise_for_status()
            content = r.json()
        else:
            if not _validate_path(source):
                return "Error: 非法路径，禁止目录穿越。"
            if not os.path.exists(source):
                return f"Error: 文件不存在 '{source}'"
            raw = open(source, "r", encoding="utf-8").read()
            if source.endswith((".yaml", ".yml")):
                import yaml
                content = yaml.safe_load(raw)
            else:
                content = json.loads(raw)
        paths = content.get("paths", {})
        summary = [
            {
                "method": m.upper(),
                "path": p,
                "summary": d.get("summary", ""),
                "parameters": [x.get("name", "?") for x in d.get("parameters", [])],
            }
            for p, ms in paths.items()
            for m, d in ms.items()
            if m.lower() in ("get", "post", "put", "delete", "patch")
        ]
        return json.dumps(summary, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error fetching API spec: {e}"


@mcp.tool()
def get_test_failure_detail(log_content: str = "", log_file: str = "") -> str:
    """解析 pytest 报错日志返回结构化失败信息。log_content 与 log_file 二选一。"""
    try:
        if log_file:
            if not _validate_path(log_file):
                return "Error: 非法路径。"
            log_content = open(log_file, "r", encoding="utf-8").read()
        if not log_content:
            return "Error: 未提供日志内容。"
        failures = [
            {
                "test_file": m.group(1),
                "test_case": m.group(2),
                "reason": (m.group(3) or "").strip(),
            }
            for m in re.finditer(
                r"FAILED\s+(\S+?)::(\S+?)(?:\s+-\s+(.+))?$",
                log_content,
                re.MULTILINE,
            )
        ]
        asserts = [
            {
                "file": m.group(1),
                "line": int(m.group(2)),
                "function": m.group(3),
                "assertion": m.group(4).strip()[:200],
            }
            for m in re.finditer(
                r"File\s+\"(.+?)\",\s+line\s+(\d+),\s+in\s+(\S+).*?assert\s+(.+)",
                log_content,
                re.DOTALL,
            )
        ]
        return json.dumps(
            {"total_failures": len(failures), "failures": failures, "assertions": asserts[:10]},
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return f"Error parsing failure log: {e}"


@mcp.tool()
def update_test_script(script_path: str, anchor: str, new_code: str) -> str:
    """根据接口变更自动修改测试脚本。anchor 为待替换的旧代码片段（需唯一匹配），new_code 为新代码。"""
    try:
        if not _validate_path(script_path) or not script_path.endswith(".py"):
            return "Error: 非法路径或非 .py 文件。"
        if not os.path.exists(script_path):
            return f"Error: 文件不存在 '{script_path}'"
        content = open(script_path, "r", encoding="utf-8").read()
        cnt = content.count(anchor)
        if cnt == 0:
            return "Error: 未找到匹配的 anchor，未做修改。"
        if cnt > 1:
            return f"Error: anchor 出现 {cnt} 次，需唯一匹配。"
        shutil.copy2(script_path, script_path + ".bak")
        line_no = content[: content.index(anchor)].count("\n") + 1
        open(script_path, "w", encoding="utf-8").write(content.replace(anchor, new_code))
        return f"Success: 已修改 '{script_path}' 第 {line_no} 行附近，备份已保存为 '{script_path}.bak'。"
    except Exception as e:
        return f"Error updating script: {e}"


@mcp.tool()
def run_pytest_code(code: str, timeout: int = 30) -> str:
    """沙箱隔离执行 pytest 代码。code 为测试代码字符串，持久化写入 tests/test_generated.py 后执行（保留文件供查看）。"""
    import sys as _sys
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests")
    test_file = os.path.join(test_dir, "test_generated.py")
    proc = None
    try:
        # 持久化测试代码到 tests/test_generated.py（保留文件，便于查看和复用）
        os.makedirs(test_dir, exist_ok=True)
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(code)
        # 保留必要环境变量，用 sys.executable -m pytest 确保用当前解释器
        keep_keys = ("PATH", "PYTHONPATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "HOME")
        env = {k: v for k, v in os.environ.items() if k.upper() in keep_keys}
        # 移除可能引起 requests 卡住的代理环境变量
        for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            env.pop(proxy_key, None)
        # 用 Popen + 进程组，确保 timeout 时能 kill 整个进程树
        import signal
        proc = subprocess.Popen(
            [_sys.executable, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header", "-x"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            proc.wait(timeout=5)
            return json.dumps({"exit_code": -1, "passed": False, "error": f"timeout after {timeout}s", "test_file": test_file}, ensure_ascii=False)
        max_len = 5000
        return json.dumps({
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "test_file": test_file,
            "stdout": stdout[-max_len:],
            "stderr": stderr[-max_len:]
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"exit_code": -1, "passed": False, "error": f"Error running pytest: {e}", "test_file": test_file}, ensure_ascii=False)


@mcp.tool()
def generate_test_report(execution_result: str, test_code: str = "", retry_count: int = 0) -> str:
    """生成 markdown 测试报告。汇总执行结果、测试代码、重试次数。"""
    try:
        result = json.loads(execution_result) if execution_result else {}
        passed = result.get("passed", False)
        exit_code = result.get("exit_code", "N/A")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        error = result.get("error", "")

        # 统计通过/失败用例数
        passed_cases = len(re.findall(r"PASSED", stdout))
        failed_cases = len(re.findall(r"FAILED", stdout))
        total = passed_cases + failed_cases
        pass_rate = f"{(passed_cases / total * 100):.1f}%" if total > 0 else "N/A"

        status = "✅ 全部通过" if passed else "❌ 存在失败"
        report = [
            f"# 测试执行报告",
            f"",
            f"## 执行状态",
            f"- 状态：{status}",
            f"- 退出码：{exit_code}",
            f"- 重试次数：{retry_count} / 3",
            f"- 用例总数：{total}",
            f"- 通过：{passed_cases}",
            f"- 失败：{failed_cases}",
            f"- 通过率：{pass_rate}",
        ]
        if error:
            report.append(f"- 错误：{error}")
        if failed_cases > 0 and stdout:
            report.append(f"\n## 失败用例摘要")
            for line in stdout.splitlines():
                if "FAILED" in line:
                    report.append(f"- {line.strip()}")
        if stderr:
            report.append(f"\n## stderr 摘要")
            report.append(f"```\n{stderr[-2000:]}\n```")
        if test_code:
            report.append(f"\n## 测试代码")
            report.append(f"```python\n{test_code[:3000]}\n```")
        report.append(f"\n---\n*报告生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(report)
    except Exception as e:
        return f"Error generating report: {e}"


if __name__ == "__main__":
    mcp.run()

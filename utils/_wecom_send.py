# _wecom_send.py - 通过 PTY 伪终端方式调用 wecom-cli msg send_message
import subprocess, json, os, sys, tempfile, time

WECOM_CLI = "wecom-cli"  # PATH 中的 wrapper

def send_wecom_message(content: str, chatid: str = "TongZhuang") -> dict:
    """通过 PTY 发送企业微信消息（绕过 Go binary 参数解析限制）"""
    payload = json.dumps({
        "chat_type": 1,
        "chatid": chatid,
        "msgtype": "text",
        "text": {"content": content}
    }, ensure_ascii=False)

    # 使用 pty + pexpect 风格的读写入
    # 在 Windows 上用 python-ptycomplex 或直接用 node pexpect
    # 最简单：用 Node.js 的 node-pty 或 ps巧妙地通过文件传输入
    
    # 方案：通过临时文件 + PowerShell Start-Process -Wait 方式
    # 但更可靠：用 Node.js child_process spawn + pty
    node_script = f"""
const {{ spawn }} = require('child_process');
const pty = require('node-pty');

const payload = JSON.stringify({payload});
const p = pty.spawn('wecom-cli', ['msg', 'send_message'], {{
    cwd: process.cwd(),
    env: process.env,
    cols: 80,
    rows: 24,
}});

let result = '';
p.onData(d => {{ result += d; }});
p.onExit(c => {{
    console.log('EXIT:' + c.exitCode);
    console.log('RESULT:' + result);
    process.exit(0);
}});

// Send JSON via stdin (Go binary reads from stdin)
p.write(payload + '\\n');
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', encoding='utf-8', delete=False) as f:
        f.write(node_script)
        js_path = f.name
    
    try:
        r = subprocess.run(
            ["node", js_path],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace"
        )
        return {"ok": "EXIT:0" in r.stdout and '"errcode": 0' in r.stdout,
                "stdout": r.stdout[:300], "stderr": r.stderr[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        os.unlink(js_path)


def send_via_node_pty(content: str, chatid: str = "TongZhuang") -> dict:
    """用 Node.js + node-pty 发送企业微信消息"""
    node_code = r"""
const { spawn } = require('child_process');
const path = require('path');

// JSON payload - passed directly as stdin
const payload = JSON.stringify({"chat_type":1,"chatid":"TongZhuang","msgtype":"text","text":{"content":"NODE_PTY_TEST"}});

const proc = spawn('wecom-cli', ['msg', 'send_message'], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: process.env,
    shell: false
});

let stdout = '';
let stderr = '';
proc.stdout.on('data', d => { stdout += d.toString(); });
proc.stderr.on('data', d => { stderr += d.toString(); });
proc.on('close', code => {
    console.log('CODE:' + code);
    console.log('OUT:' + stdout.substring(0, 500));
    console.log('ERR:' + stderr.substring(0, 200));
});
proc.stdin.write(payload + '\n');
proc.stdin.end();
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', encoding='utf-8', delete=False) as f:
        f.write(node_code)
        js_path = f.name
    
    try:
        r = subprocess.run(["node", js_path],
            capture_output=True, text=True, timeout=20)
        return {"ok": r.returncode == 0 and '"errcode": 0' in r.stdout,
                "stdout": r.stdout[:300], "stderr": r.stderr[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        os.unlink(js_path)


if __name__ == "__main__":
    print("=== PTY/Stdin 方式测试 ===")
    # Test: 用 Node.js child_process spawn (no PTY)
    r = send_via_node_pty("Node_spawn_stdin_test")
    print(f"Node spawn stdin: OK={r['ok']}")
    print(f"  stdout: {r.get('stdout','')[:200]}")
    print(f"  stderr: {r.get('stderr','')[:200]}")

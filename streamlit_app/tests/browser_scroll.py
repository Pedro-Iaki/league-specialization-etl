"""Exercise the served clone through Edge CDP; never select a backup storyboard tab."""

import asyncio
import json
from pathlib import Path

import requests
from websockets.asyncio.client import connect

HERE = Path(__file__).resolve().parents[2] / "sandbox/streamlit_story_validation.tmp"
HERE.mkdir(exist_ok=True)
(HERE / "evidence").mkdir(exist_ok=True)
URL = "http://127.0.0.1:8510/"


async def main():
    targets = (await asyncio.to_thread(requests.get, "http://127.0.0.1:9251/json", timeout=3)).json()
    target = next((x for x in targets if x["type"] == "page" and x["url"] == URL), None)
    if target is None:
        target = (await asyncio.to_thread(requests.put, "http://127.0.0.1:9251/json/new?" + URL, timeout=3)).json()
    cases = []
    errors = []
    async with connect(target["webSocketDebuggerUrl"], max_size=30_000_000) as ws:
        seq = 0

        async def call(method, params=None):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("method") == "Runtime.exceptionThrown":
                    errors.append(msg)
                if msg.get("id") == seq:
                    assert "error" not in msg, msg
                    return msg["result"]

        async def js(code):
            r = await call(
                "Runtime.evaluate",
                {
                    "expression": "document.querySelector('iframe').contentWindow.eval(" + json.dumps(code) + ")",
                    "returnByValue": True,
                },
            )
            assert "exceptionDetails" not in r, r
            return r["result"].get("value")

        async def wait():
            for _ in range(600):
                if await js("!waiting"):
                    break
                await asyncio.sleep(0.05)
            assert await js("!waiting && !error"), await js("error")

        async def question(q):
            await js(
                f"document.getElementById('exampleQuestion').value='{q}';document.getElementById('exampleQuestion').dispatchEvent(new Event('change'))"
            )
            await wait()

        async def check(tag):
            assert not await js("document.documentElement.scrollWidth>innerWidth"), tag
            assert not await js("/NaN|undefined|Infinity/.test(document.getElementById('content').textContent)"), tag
            assert await js("!document.querySelector('[data-carry]')&&!document.querySelector('[data-mode]')"), tag
            if await js("Boolean(current)"):
                assert await js("document.querySelectorAll('[data-audience]').length===2"), tag
                assert await js(
                    "[...document.querySelectorAll('[data-audience]')].every(c=>c.querySelectorAll('h2').length===1)"
                ), tag
            cases.append(tag)

        await call("Page.reload", {"ignoreCache": True})
        await asyncio.sleep(0.5)
        for _ in range(600):
            r = await call(
                "Runtime.evaluate",
                {
                    "expression": "Boolean(document.querySelector('iframe')?.contentWindow.eval('typeof E!==\"undefined\" && E'))",
                    "returnByValue": True,
                },
            )
            if r.get("result", {}).get("value"):
                break
            await asyncio.sleep(0.05)
        for width in [1440, 390]:
            await call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False},
            )
            await asyncio.sleep(0.2)
            for chapter in range(1, 8):
                await js(f"go({chapter});document.body.scrollTop=0")
                await wait()
                await call(
                    "Input.dispatchMouseEvent",
                    {"type": "mouseWheel", "x": width // 2, "y": 300, "deltaX": 0, "deltaY": 550},
                )
                await asyncio.sleep(0.25)
                assert await js("document.body.scrollTop>0"), (width, chapter, "wheel")
                await js("document.body.scrollTop=document.body.scrollHeight")
                assert await js('document.querySelector("footer").getBoundingClientRect().bottom<=innerHeight+1'), (
                    width,
                    chapter,
                    "footer",
                )
                await js("document.body.scrollTop=0")
                cases.append([width, chapter, "wheel-and-footer"])
            await js("go(1)")
            await call("Runtime.evaluate", {"expression": "document.querySelector('iframe').focus()"})
            await js('document.querySelector("[data-page]").focus()')
            await call(
                "Input.dispatchKeyEvent",
                {"type": "keyDown", "key": "PageDown", "code": "PageDown", "windowsVirtualKeyCode": 34},
            )
            await asyncio.sleep(0.3)
            assert await js("document.body.scrollTop>0"), (width, "keyboard")
            await js("go(2)")
            assert await js("document.body.scrollTop===0"), (width, "navigation-reset")
        (HERE / "scroll-validation.json").write_text(
            json.dumps({"cases": cases, "keyboard": True, "navigation_reset": True}, indent=2), encoding="utf8"
        )
        await call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False},
        )
        await js("go(1);document.body.scrollTop=0")
        print(
            "Mouse wheel and footer reach passed on all seven chapters at both widths; PageDown and navigation reset passed."
        )


if __name__ == "__main__":
    asyncio.run(main())

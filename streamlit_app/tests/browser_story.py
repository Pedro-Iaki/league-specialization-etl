"""Exercise the served clone through Edge CDP; never select a backup storyboard tab."""

import asyncio
import base64
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

        await call("Runtime.enable")
        errors.clear()
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
        else:
            raise AssertionError("Streamlit component did not initialize")
        errors.clear()
        for width in [1440, 390]:
            await call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width == 390},
            )
            for terms in ["plain", "precise"]:
                for n in range(1, 8):
                    await js(f"document.querySelector('[data-page=\"{n}\"]').click()")
                    await wait()
                    await js(
                        f"document.getElementById('terms').value='{terms}';document.getElementById('terms').dispatchEvent(new Event('change'))"
                    )
                    await check([width, terms, n, "overview"])
                    if n in [2, 3, 4, 6]:
                        qs = await js(
                            "[...document.querySelectorAll('#exampleQuestion option')].map(x=>x.value).filter(x=>x&&x!=='custom')"
                        )
                        for q in qs:
                            await question(q)
                            await check([width, terms, n, q])
                            options = (
                                await js("example().options.map(x=>x.id)")
                                if width == 1440 and terms == "plain" and n == await js("example().first_page")
                                else []
                            )
                            await js(
                                "if(!document.getElementById('guided-settings').open)document.querySelector('#guided-settings summary').click()"
                            )
                            for option in options:
                                await js(
                                    f"document.querySelector('[data-adjust=a]').value='{option}';document.querySelector('[data-adjust=a]').dispatchEvent(new Event('change'))"
                                )
                                await wait()
                                assert await js("document.getElementById('guided-settings').open")
                            await question("")
                    if n == 4:
                        await js("document.querySelector('#family-method summary').click()")
                        for idx in [1, 24]:
                            await js(
                                f"document.getElementById('familyChoice').value='{idx}';document.getElementById('familyChoice').dispatchEvent(new Event('change'))"
                            )
                            assert await js("document.getElementById('family-method').open")
                        await js(
                            "document.querySelector('#component-method summary').click();document.getElementById('componentChoice').value='3';document.getElementById('componentChoice').dispatchEvent(new Event('change'))"
                        )
                        assert await js("document.getElementById('component-method').open && componentIndex===3")
                        await js(
                            "document.querySelector('#overlap-example summary').click();document.querySelector('#overlap-example button').click()"
                        )
                        assert await js(
                            "document.getElementById('overlap-example').open && document.getElementById('family-method').open"
                        )
                    if n == 5:
                        await js(
                            "if(!document.getElementById('builder-shared').open)document.querySelector('#builder-shared summary').click();document.querySelector('[data-filter=\"shared.history_band.H5\"]').click()"
                        )
                        assert await js("pending && !current.definition.shared.history_band")
                        await js("document.querySelector('[data-apply]').click()")
                        await wait()
                        assert await js("!pending && current.definition.shared.history_band[0]==='H5'")
                        await js(
                            "document.querySelector('#joint-view summary').click();document.querySelector('[data-axis=\"0\"]').value='history_band';document.querySelector('[data-axis=\"0\"]').dispatchEvent(new Event('change'))"
                        )
                        await wait()
                        assert await js(
                            "current.definition.joint_axes[0]==='history_band' && document.getElementById('joint-view').open"
                        )
                        await check([width, terms, n, "custom"])
                        await js("document.getElementById('next').click()")
                        assert await js("page===6&&qid==='custom'&&current.definition.shared.history_band[0]==='H5'")
                        await check([width, terms, 6, "inherited-custom"])
                        await js("document.getElementById('prev').click()")
                        await wait()
                        assert await js("page===5&&!current.definition.shared.history_band")
                        await js(
                            "document.querySelector('[data-clear]').click();document.querySelector('[data-apply]').click()"
                        )
                        await wait()
                        assert await js("current.identical")
                    if n == 7:
                        await js(
                            "document.querySelector('#run-evidence summary').click();document.getElementById('runChoice').value='0';document.getElementById('runChoice').dispatchEvent(new Event('change'))"
                        )
                        assert await js("document.getElementById('run-evidence').open && runIndex===0")
                    if terms == "plain" and n in [4, 5, 6, 7]:
                        if n == 4:
                            await question("interests")
                        await asyncio.sleep(0.2)
                        size = (await call("Page.getLayoutMetrics"))["cssContentSize"]
                        shot = await call(
                            "Page.captureScreenshot",
                            {
                                "format": "png",
                                "captureBeyondViewport": False,
                                "clip": {"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1},
                            },
                        )
                        (HERE / "evidence" / f"v2-{width}-page-{n}.png").write_bytes(base64.b64decode(shot["data"]))
        # Real browser network failure and late response; old labels cannot show new data.
        await js("go(2)")
        await call("Network.enable")
        for width in [1440, 390]:
            await call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width == 390},
            )
            await js("go(5)")
            await wait()
            await js(
                "if(!document.getElementById('builder-shared').open)document.querySelector('#builder-shared summary').click();document.querySelector('[data-filter=\"shared.history_band.H5\"]').click()"
            )
            for field, values in [("activity_band", ["A4", "A5"]), ("engagement_band", ["E3", "E4"])]:
                await js(
                    "if(!document.getElementById('builder-a').open)document.querySelector('#builder-a summary').click()"
                )
                for value in values:
                    await js(f"document.querySelector('[data-filter=\"a.{field}.{value}\"]').click()")
            await js(
                "if(!document.getElementById('builder-a').open)document.querySelector('#builder-a summary').click();document.querySelector('[data-interest-mode=a]').value='expressed';document.querySelector('[data-interest-mode=a]').dispatchEvent(new Event('change'));document.querySelector('[data-interest=\"a.A1\"]').click();document.querySelector('[data-interest=\"a.A3\"]').click()"
            )
            await js("document.querySelector('[data-apply]').click()")
            await wait()
            assert await js(
                "current.a.profiles>30&&current.definition.a.archetype.mode==='expressed'&&current.definition.a.archetype.ids.length===2"
            )
            await check([width, "three-dimensions-plus-expressed"])
            await js(
                "document.querySelector('#joint-view summary').click();document.querySelector('[data-axis=\"1\"]').value='engagement_band';document.querySelector('[data-axis=\"1\"]').dispatchEvent(new Event('change'))"
            )
            await wait()
            assert await js("current.definition.joint_axes[1]==='engagement_band'")
            await js(
                "if(!document.getElementById('builder-a').open)document.querySelector('#builder-a summary').click();document.querySelector('[data-filter=\"a.rank_group.High\"]').click()"
            )
            assert await js("pending")
            await js(
                "document.querySelector('[data-axis=\"0\"]').value='history_band';document.querySelector('[data-axis=\"0\"]').dispatchEvent(new Event('change'))"
            )
            await wait()
            assert await js("pending&&!current.definition.a.rank_group")
            await js("document.getElementById('next').click()")
            assert await js(
                "page===6&&current.definition.a.archetype.mode==='expressed'&&!current.definition.a.rank_group"
            )
            await check([width, "carry-applied-not-pending"])
            await js("go(5)")
            await wait()
            await js("document.querySelector('[data-clear]').click()")
            await js(
                "if(!document.getElementById('builder-shared').open)document.querySelector('#builder-shared summary').click();document.querySelector('#filter-shared-archetype_state summary').click();document.querySelector('[data-filter=\"shared.archetype_state.empty_pool\"]').click();if(!document.getElementById('builder-a').open)document.querySelector('#builder-a summary').click();document.querySelector('[data-interest=\"a.A1\"]').click();document.querySelector('[data-apply]').click()"
            )
            await wait()
            assert await js("current.a.profiles===0&&current.b.archetypes.scored===0")
            await check([width, "empty-unscored"])
            await js("document.querySelector('[data-clear]').click();document.querySelector('[data-apply]').click()")
            await wait()
            assert await js("current.identical")
            await check([width, "identical-all"])
        for width in [1440, 390]:
            await call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 1050, "deviceScaleFactor": 1, "mobile": width == 390},
            )
            await js("go(1);go(5)")
            await wait()
            assert await js(
                "document.getElementById('builder-a').open && !document.getElementById('builder-shared').open"
            )
            await js(
                "document.querySelector('[data-filter=\"a.history_band.H5\"]').click();document.querySelector('[data-filter=\"a.history_band.H4\"]').click()"
            )
            assert await js("draft.a.history_band.length===2 && pending && !current.definition.a.history_band")
            await js(
                "document.querySelector('[data-filter=\"a.history_band.H4\"]').click();document.querySelector('#builder-a>summary').click();document.querySelector('#builder-a>summary').click()"
            )
            assert await js(
                "draft.a.history_band.length===1 && document.querySelector('[data-filter=\"a.history_band.H5\"]').getAttribute('aria-pressed')==='true'"
            )
            await js(
                "document.querySelector('#filter-a-archetype_kind>summary').click();document.querySelector('[data-filter=\"a.archetype_kind.Blend\"]').click();document.querySelector('[data-filter=\"a.archetype_kind.Single\"]').click()"
            )
            assert await js(
                "draft.a.archetype_kind.length===2 && document.querySelector('#filter-a-archetype_kind>summary').textContent.includes('2 selected')"
            )
            await call("Runtime.evaluate", {"expression": "document.querySelector('iframe').focus()"})
            await js("document.querySelector('#filter-a-archetype_kind>summary').focus()")
            await call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape"})
            assert await js(
                "!document.getElementById('filter-a-archetype_kind').open && document.activeElement===document.querySelector('#filter-a-archetype_kind>summary')"
            )
            await js("document.querySelector('#filter-a-archetype_state>summary').click()")
            assert not await js("document.documentElement.scrollWidth>innerWidth")
            await js("document.querySelector('.builder-start').click()")
            assert await js("!document.getElementById('filter-a-archetype_state').open")
            await js(
                "document.querySelector('[data-primary=a]').click();document.querySelector('[data-interest=\"a.A1\"]').click();document.querySelector('[data-interest=\"a.A3\"]').click();document.querySelector('[data-interest-mode=a]').value='expressed';document.querySelector('[data-interest-mode=a]').dispatchEvent(new Event('change'))"
            )
            assert await js(
                "draft.a.primary_required && draft.a.archetype.ids.length===2 && draft.a.archetype.mode==='expressed'"
            )
            await js(
                "document.querySelector('#filter-a-archetype_kind>summary').click();document.getElementById('terms').value='precise';document.getElementById('terms').dispatchEvent(new Event('change'))"
            )
            assert await js(
                "pending && document.getElementById('filter-a-archetype_kind').open && document.querySelector('[data-primary=a]').checked && !current.definition.a.archetype"
            )
            await js(
                "document.querySelector('#builder-a>summary').click();document.querySelector('[data-apply]').click()"
            )
            await wait()
            assert await js(
                "!pending && !document.getElementById('builder-a').open && current.definition.a.archetype.ids.length===2 && current.definition.a.primary_required"
            )
            await js("document.querySelector('[data-clear]').click()")
            assert await js(
                "pending && document.querySelectorAll('.segments button[aria-pressed=true]').length===0 && [...document.querySelectorAll('.audience-builder input')].every(i=>!i.checked) && [...document.querySelectorAll('[data-builder-summary]')].every(s=>s.textContent==='All observed profiles')"
            )
            await js("document.querySelector('[data-apply]').click()")
            await wait()
            assert await js("current.identical && current.a.profiles===38403")
            await js(
                "document.getElementById('builderPreset').value='interests';document.getElementById('builderPreset').dispatchEvent(new Event('change'))"
            )
            assert await js("pending && document.getElementById('builderPreset').value==='interests'")
            await js("document.querySelector('[data-apply]').click()")
            await wait()
            assert await js("current.a.profiles===2357 && current.b.profiles===2736")
            await check([width, "approved-controls-and-canonical-counts"])
            await js("document.querySelector('#builder-a>summary').click()")
        await js("go(1);go(5)")
        await wait()
        await js(
            "window.savedRequest=requestComparison;requestComparison=async d=>{const r=await savedRequest(d);await new Promise(resolve=>setTimeout(resolve,500));return r;};document.querySelector('[data-apply]').click();document.querySelector('[data-filter=\"b.rank_group.High\"]').click()"
        )
        await wait()
        assert await js("pending && !current.definition.b.rank_group && draft.b.rank_group.includes('High')")
        await js("requestComparison=savedRequest;go(2);query({schema_version:1,a:{invalid:[]}})")
        for _ in range(600):
            if await js("!waiting"):
                break
            await asyncio.sleep(0.05)
        assert await js("Boolean(error)&&!current")
        await question("participation")
        await js(
            "window.originalRequest=requestComparison;requestComparison=async d=>{const r=await originalRequest(d);await new Promise(resolve=>setTimeout(resolve,500));return r;};chooseQuestion('participation');go(3)"
        )
        await asyncio.sleep(1)
        assert await js("page===3&&!current&&!qid")
        await js("requestComparison=originalRequest;go(1)")
        await call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False},
        )
        assert not errors, errors
        (HERE / "browser-validation.json").write_text(
            json.dumps(
                {
                    "cases": cases,
                    "errors": errors,
                    "invalid_request_recovery": True,
                    "late_response": True,
                    "edits_in_flight": True,
                },
                indent=2,
            ),
            encoding="utf8",
        )
        print(
            f"Passed {len(cases)} Streamlit browser states, guided options, builder boundaries, disclosure controls, invalid-request recovery and in-flight edits."
        )


if __name__ == "__main__":
    asyncio.run(main())

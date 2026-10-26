"""Exercise the served clone through Edge CDP; never select a backup storyboard tab."""

import asyncio
import json
import sys
from pathlib import Path

import requests
from websockets.asyncio.client import connect

HERE = Path(__file__).resolve().parents[2] / "sandbox/streamlit_story_validation.tmp"
HERE.mkdir(exist_ok=True)
(HERE / "evidence").mkdir(exist_ok=True)
URL = "http://127.0.0.1:8510/"
PUBLISHED = "--published" in sys.argv
TEST_LOCALE = "pt-BR" if PUBLISHED else "test"


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
        assert await js("StoryI18n.locale===E.localization.defaultLocale && !document.getElementById('language-control').hidden")
        await js("window.originalCatalog=copy(E.localization)")
        if not PUBLISHED:
            await js(
                "window.testCatalog=copy(E.localization);testCatalog.locales.push({id:'test',label:'Test locale',formatLocale:'pt-BR',status:'ready'});testCatalog.messages.test=Object.fromEntries(Object.entries(testCatalog.messages.en).map(([k,v])=>[k,'⟦'+v+'⟧']));StoryI18n.configure(testCatalog)"
            )
        await js("setLocale('en')")
        await js("go(4);chooseQuestion('interests')")
        await wait()
        await js(
            "document.querySelector('#family-method summary').click();document.querySelector('#component-method summary').click();document.getElementById('componentChoice').value='3';document.getElementById('componentChoice').dispatchEvent(new Event('change'));window.beforeLocale=JSON.stringify(current);document.getElementById('language').value=" + json.dumps(TEST_LOCALE) + ";document.getElementById('language').dispatchEvent(new Event('change'))"
        )
        assert await js(
            "JSON.stringify(current)===beforeLocale && qid==='interests' && componentIndex===3 && document.getElementById('family-method').open && document.getElementById('component-method').open && document.documentElement.lang===" + json.dumps(TEST_LOCALE)
        )
        assert await js("PCT(.123)==='12,3%' && money(1234.5).includes('1.234,50')")
        raw_text = {}
        for width in [1440, 390]:
            await call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
            )
            await asyncio.sleep(0.2)
            for terms in ["plain", "precise"]:
                for chapter in range(1, 8):
                    await js(
                        f"go({chapter});document.getElementById('terms').value='{terms}';document.getElementById('terms').dispatchEvent(new Event('change'))"
                    )
                    await wait()
                    if chapter in [2, 3, 4, 6]:
                        q = await js("[...document.querySelectorAll('#exampleQuestion option')].at(-1).value")
                        await js(f"chooseQuestion('{q}')")
                        await wait()
                    await js("document.querySelectorAll('details').forEach(d=>d.open=true)")
                    assert not await js("document.documentElement.scrollWidth>innerWidth"), (width, terms, chapter)
                    if PUBLISHED and width == 1440:
                        oversized = await js("[...document.querySelectorAll('.diagram-wide svg a')].flatMap(a=>[...a.querySelectorAll('text')].filter(t=>t.getBBox().width>a.querySelector('rect').getBBox().width-12).map(t=>({text:t.textContent,width:t.getBBox().width})))")
                        assert not oversized, (width, terms, chapter, oversized)
                    assert await js(
                        "!document.body.textContent.includes('undefined') && !document.body.textContent.includes('NaN')"
                    )
                    raw = await js(
                        "(()=>{const out=[];const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;while(n=walk.nextNode()){if(['SCRIPT','STYLE','OPTION'].includes(n.parentElement.tagName))continue;const text=n.textContent.trim();if(/[A-Za-z]{3}/.test(text)&&!text.includes('⟦'))out.push(text);}return [...new Set(out)];})()"
                    )
                    protected = await js(
                        "['players-as-customers-pipeline','Pedro Iaki','Python',...E.methods.families.flatMap(f=>f.members.map(m=>m.name))]"
                    )
                    if PUBLISHED:
                        # Exact untranslated source messages, excluding shared proper names/notation.
                        raw = await js("(()=>{const c=StoryI18n.catalog.messages;const english=new Set(Object.keys(c.en).filter(k=>c.en[k]!==c['pt-BR'][k]).map(k=>c.en[k]));const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);const out=[];let n;while(n=walk.nextNode())if(!['SCRIPT','STYLE'].includes(n.parentElement.tagName)&&english.has(n.textContent.trim()))out.push(n.textContent.trim());return out;})()")
                    assert (not raw if PUBLISHED else all(text in protected or (text[:1].isdigit() and text.endswith(" UTC")) for text in raw)), (
                        width,
                        terms,
                        chapter,
                        raw,
                    )
                    raw_text[str((width, terms, chapter))] = raw
                    cases.append([width, terms, chapter])
        await js("go(1);go(5)")
        await wait()
        await js(
            "document.querySelector('[data-filter=\"a.rank_group.High\"]').click();document.querySelector('[data-interest=\"a.A1\"]').click();document.querySelector('#filter-a-archetype_kind summary').click();document.body.scrollTop=350;window.draftBefore=JSON.stringify(draft);window.appliedBefore=JSON.stringify(current);window.savedComparison=requestComparison;window.localeRequests=0;requestComparison=d=>{localeRequests++;return savedComparison(d);};document.getElementById('language').value='en';document.getElementById('language').dispatchEvent(new Event('change'))"
        )
        assert await js(
            "pending && JSON.stringify(draft)===draftBefore && JSON.stringify(current)===appliedBefore && localeRequests===0 && document.getElementById('filter-a-archetype_kind').open && document.body.scrollTop===350"
        )
        await js(
            "window.delayedComparison=requestComparison;requestComparison=async d=>{const result=await delayedComparison(d);await new Promise(resolve=>setTimeout(resolve,500));return result;};document.querySelector('[data-apply]').click();setLocale(" + json.dumps(TEST_LOCALE) + ")"
        )
        await wait()
        assert await js(
            "!pending && current.definition.a.rank_group[0]==='High' && current.definition.a.archetype.ids[0]==='A1' && StoryI18n.locale===" + json.dumps(TEST_LOCALE)
        )
        await js("requestComparison=savedComparison;StoryI18n.configure(originalCatalog);setLocale(originalCatalog.defaultLocale);go(1)")
        await call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False},
        )
        (HERE / ("portuguese-validation.json" if PUBLISHED else "localization-validation.json")).write_text(
            json.dumps(
                {
                    "cases": cases,
                    "unmarked_text": raw_text,
                    "state_preserved": True,
                    "locale_did_not_query": True,
                    "switch_during_query": True,
                    "published_portuguese": PUBLISHED,
                },
                indent=2,
            ),
            encoding="utf8",
        )
        assert not errors, errors
        print(
            f"28 {TEST_LOCALE} chapter/layout states, formatting, state/disclosure/scroll preservation and switching during a query passed."
        )


if __name__ == "__main__":
    asyncio.run(main())

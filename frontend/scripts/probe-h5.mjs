/**
 * H5 界面探测：用无头 Chrome（CDP）打开 dev server，点一次场景切换，对比前后 DOM 与控制台错误。
 *
 * 为什么需要它：这个项目没有前端自动化测试，而"界面只更新一半"这类问题
 * **靠读代码推不出来**——渲染中途抛错会让 DOM 停在半新半旧的状态。
 * 本脚本用真浏览器跑一遍，把"胶囊 / 对话区标题 / 表单字段 / 两处必填提示"一并读出来对比。
 *
 * 用法（先确保 dev server 已在 5173 跑起来）：
 *
 *   # 1) 起一个无头 Chrome（headless=new + 远程调试端口）
 *   "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
 *     --headless=new --disable-gpu --remote-debugging-port=9222 ^
 *     --user-data-dir=..\data\runtime\cc-probe --no-first-run ^
 *     --no-default-browser-check http://127.0.0.1:5173/
 *
 *   # 2) 跑探测（Node 20 需要显式打开 WebSocket）
 *   node --experimental-websocket scripts/probe-h5.mjs 9222
 *
 * 判定标准：点「开办企业」后，胶囊应变成「开办企业[*]」、对话区标题应为「开办企业一件事」、
 * 表单字段应变成 7 个企业字段、提示应为 3 项企业字段，且**控制台无 error**。
 */
const PORT = Number(process.argv[2] || 9222)

const PROBE = `
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (el) => (el ? el.textContent.trim() : null);
  const read = () => ({
    chips: [...document.querySelectorAll('.app__scenarios .chip')]
      .map((e) => e.textContent.trim() + (e.className.indexOf('chip--on') >= 0 ? '[*]' : '')),
    对话区标题: txt(document.querySelector('.chat__sub')),
    表单字段: [...document.querySelectorAll('.field__label')].map((e) => e.textContent.trim()),
    表单内提示: txt(document.querySelector('.form__hint')),
    按钮区提示: txt(document.querySelector('.actions__hint')),
    预判: txt(document.querySelector('.preview__title')),
  });
  await sleep(2000);
  const before = read();
  const chips = [...document.querySelectorAll('.app__scenarios .chip')];
  const clicked = chips[1] ? chips[1].textContent.trim() : '(找不到第 2 个胶囊)';
  if (chips[1]) chips[1].click();
  await sleep(2500);
  return JSON.stringify({ 点了哪个: clicked, 点之前: before, 点之后: read() }, null, 1);
})()
`

async function waitForPage(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch('http://127.0.0.1:' + PORT + '/json')
      const list = await res.json()
      const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      if (page) return page
    } catch (e) {
      // DevTools 端口还没起来，继续等
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('等不到可用的页面目标（无头浏览器起了吗？端口对吗？）')
}

const page = await waitForPage()
const ws = new WebSocket(page.webSocketDebuggerUrl)
const pending = new Map()
const consoleErrors = []
let seq = 0

function send(method, params) {
  return new Promise((resolve) => {
    const id = ++seq
    pending.set(id, resolve)
    ws.send(JSON.stringify({ id, method, params }))
  })
}

ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data)
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg)
    pending.delete(msg.id)
    return
  }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    consoleErrors.push(
      msg.params.args.map((a) => a.value || a.description || '').join(' ')
    )
  }
})

await new Promise((resolve) => ws.addEventListener('open', resolve))
await send('Runtime.enable')

const result = await send('Runtime.evaluate', {
  expression: PROBE,
  awaitPromise: true,
  returnByValue: true
})

console.log('===== 探测结果 =====')
const value = result.result && result.result.result && result.result.result.value
console.log(value || JSON.stringify(result))
if (consoleErrors.length) {
  console.log('===== 控制台错误（有错就说明渲染中途断了）=====')
  consoleErrors.slice(0, 10).forEach((line) => console.log('- ' + line))
} else {
  console.log('===== 控制台无 error =====')
}
ws.close()

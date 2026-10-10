/**
 * 助手页：把 /api/v1/dingtalk/chat 的 SSE 事件流渲染成一条「操作流水」。
 *
 * 和普通聊天窗口的区别在于，模型每次调用钉钉操作都会在时间轴上留下一条记录，
 * 并标明这次是「只读取」还是「会发出去」——用户能看清助手到底动了什么。
 */
(function () {
  "use strict";

  const DT = window.DT;

  const dom = {
    ledger: document.getElementById("ledger"),
    asks: document.getElementById("asks"),
    form: document.getElementById("composer"),
    input: document.getElementById("ask"),
    send: document.getElementById("send"),
    stamp: document.getElementById("stamp"),
  };

  const PROMPTS = [
    "看看我今天有什么待办",
    "我今天的日程安排是什么",
    "我今天打卡了吗",
    "查一下我收到的日志",
    "搜索联系人：张三",
  ];

  let seq = 0;
  let busy = false;
  let emptyHint = null;

  function nextNo() {
    seq += 1;
    return String(seq).padStart(2, "0");
  }

  /** 新建一条流水记录，返回可继续填充的内容容器。 */
  function entry(classes, label) {
    const item = document.createElement("li");
    item.className = classes;
    item.innerHTML = '<span class="entry__slot"><span class="node"></span></span>';

    const body = document.createElement("div");
    body.className = "entry__body";

    const no = document.createElement("span");
    no.className = "entry__no";
    no.textContent = `${nextNo()} · ${label}`;
    body.append(no);

    item.append(body);
    dom.ledger.append(item);
    return body;
  }

  function scrollToBottom() {
    const last = dom.ledger.lastElementChild;
    if (last) last.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function dropEmptyHint() {
    if (emptyHint) {
      emptyHint.remove();
      emptyHint = null;
    }
  }

  function showEmptyHint() {
    emptyHint = document.createElement("li");
    emptyHint.className = "ledger__empty";
    emptyHint.textContent =
      "还没有操作记录。挑下面一句试试——助手会先调钉钉取数或办事，再把结果讲给你听。";
    dom.ledger.append(emptyHint);
  }

  function pushYou(text) {
    const body = entry("entry entry--you", "你说");
    const said = document.createElement("p");
    said.className = "said";
    said.textContent = text;
    body.append(said);
  }

  function pushTool(name, args) {
    const meta = DT.TOOLS[name] || { label: name, write: false };
    const body = entry(`entry entry--tool${meta.write ? " is-write" : ""}`, "调用钉钉操作");

    const call = document.createElement("p");
    call.className = "call";

    const title = document.createElement("span");
    title.className = "call__name";
    title.textContent = meta.label;
    call.append(title);

    const params = DT.argsText(args);
    if (params) {
      const argsEl = document.createElement("span");
      argsEl.className = "call__args";
      argsEl.textContent = params;
      call.append(argsEl);
    }

    const flag = document.createElement("span");
    flag.className = "call__flag";
    flag.textContent = meta.write ? "会发出去" : "只读取";
    call.append(flag);

    body.append(call);
  }

  /** 逐帧渲染流式回答，避免每个分片都触发一次重排。 */
  function makeAnswerWriter(body) {
    const answer = document.createElement("div");
    answer.className = "answer";
    body.append(answer);

    let raw = "";
    let scheduled = false;

    function draw(withCursor) {
      scheduled = false;
      answer.innerHTML = `${DT.formatRich(raw)}${withCursor ? '<span class="cursor"></span>' : ""}`;
    }

    return {
      append(chunk) {
        raw += chunk;
        if (!scheduled) {
          scheduled = true;
          requestAnimationFrame(() => draw(true));
        }
      },
      finish() {
        draw(false);
      },
      isBlank() {
        return !raw.trim();
      },
      text() {
        return raw;
      },
    };
  }

  function drawFailure(body, message, advice, detail) {
    body.innerHTML = "";
    const no = document.createElement("span");
    no.className = "entry__no";
    no.textContent = `${nextNo()} · 助手`;
    body.append(no);

    const box = document.createElement("div");
    box.className = "answer answer--error";

    const line = document.createElement("p");
    line.textContent = message;
    box.append(line);

    if (advice) {
      const tip = document.createElement("p");
      tip.textContent = advice;
      box.append(tip);
    }
    if (detail) {
      const raw = document.createElement("p");
      raw.textContent = detail;
      box.append(raw);
    }
    body.append(box);
  }

  /** 读取 SSE 帧并逐条交给 onEvent。 */
  async function streamChat(question, onEvent) {
    const response = await fetch(`${DT.API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`服务返回 HTTP ${response.status}，没能开始生成。`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    function drain(frame) {
      const line = frame.split("\n").find((item) => item.startsWith("data:"));
      if (!line) return;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        /* 坏帧直接跳过，不影响整条流 */
      }
    }

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      frames.forEach(drain);
    }
    if (buffer.trim()) drain(buffer);
  }

  async function ask(question) {
    const text = String(question || "").trim();
    if (!text || busy) return;

    busy = true;
    dom.send.disabled = true;
    dom.input.value = "";
    dropEmptyHint();
    pushYou(text);
    scrollToBottom();

    let body = null;
    let writer = null;
    let failure = "";

    try {
      await streamChat(text, (payload) => {
        if (payload.type === "tool") {
          pushTool(payload.name, payload.args);
          scrollToBottom();
          return;
        }
        if (payload.type === "content") {
          if (!body) {
            body = entry("entry entry--agent", "助手");
            writer = makeAnswerWriter(body);
          }
          writer.append(payload.content || "");
          return;
        }
        if (payload.type === "error") {
          failure = payload.message || "生成过程出错。";
        }
      });
    } catch (error) {
      failure = error.message || "请求没能送达服务。";
    }

    if (writer) writer.finish();

    if (failure) {
      if (body && writer && !writer.isBlank()) {
        const note = document.createElement("p");
        note.className = "answer--error";
        note.textContent = `这次没能办完：${failure}`;
        body.append(note);
      } else {
        if (body) body.parentElement?.remove();
        const fallback = entry("entry entry--agent", "助手");
        drawFailure(fallback, `这次没能办完：${failure}`, "确认 dws 已安装并登录后重试。", "");
      }
    } else if (!body) {
      const fallback = entry("entry entry--agent", "助手");
      drawFailure(fallback, "助手这次没有给出内容。", "换个说法再问一次，或到操作台直接调用接口。", "");
    }

    scrollToBottom();
    busy = false;
    dom.send.disabled = false;
    dom.input.focus();
  }

  function renderPrompts() {
    const frag = document.createDocumentFragment();
    PROMPTS.forEach((text) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "ask";
      chip.textContent = text;
      chip.addEventListener("click", () => ask(text));
      frag.append(chip);
    });
    dom.asks.replaceChildren(frag);
  }

  function bind() {
    dom.form.addEventListener("submit", (event) => {
      event.preventDefault();
      ask(dom.input.value);
    });

    dom.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        ask(dom.input.value);
      }
    });
  }

  async function init() {
    renderPrompts();
    bind();
    showEmptyHint();
    DT.paintStamp(dom.stamp, await DT.loadStatus());
  }

  init();
})();

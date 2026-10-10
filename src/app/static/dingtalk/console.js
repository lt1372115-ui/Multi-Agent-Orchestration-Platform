/**
 * 操作台页：把 dingtalk.py 里的直连接口逐个做成卡片。
 *
 * 「查一查」里的卡片只读取信息，「做一做」里的卡片会真的发出去——
 * 后者必须先在卡片内勾选确认，才会调用接口，对应后端的 confirm 字段。
 */
(function () {
  "use strict";

  const DT = window.DT;

  const dom = {
    readCards: document.getElementById("readCards"),
    writeCards: document.getElementById("writeCards"),
    stamp: document.getElementById("stamp"),
    railDws: document.getElementById("railDws"),
    railUser: document.getElementById("railUser"),
    railLogin: document.getElementById("railLogin"),
    railRefresh: document.getElementById("railRefresh"),
    railRawToggle: document.getElementById("railRawToggle"),
    railRaw: document.getElementById("railRaw"),
    drawer: document.getElementById("drawer"),
    drawerVerb: document.getElementById("drawerVerb"),
    drawerPath: document.getElementById("drawerPath"),
    drawerMeta: document.getElementById("drawerMeta"),
    drawerBody: document.getElementById("drawerBody"),
    drawerClose: document.getElementById("drawerClose"),
  };

  const BODY_LIMIT = 6000;

  // ---------------- 接口清单（与 src/app/api/v1/dingtalk.py 一一对应） ----------------

  const READ_CARDS = [
    {
      path: "/contact/search",
      name: "搜索联系人",
      action: "搜索",
      desc: "按姓名或关键词查人，拿到 userId、部门、职位、手机号。",
      fields: [{ name: "query", label: "关键词", placeholder: "张三", required: true, hint: "姓名、花名或关键词" }],
    },
    {
      path: "/calendar/list",
      name: "今天的日程",
      action: "查询",
      desc: "读取今天的会议与日程安排。",
      fields: [],
    },
    {
      path: "/todo/list",
      name: "我的待办",
      action: "查询",
      desc: "读取待办清单，可以连已完成的也一起看。",
      fields: [
        { name: "include_done", label: "连已完成的也返回", type: "checkbox" },
        { name: "priority", label: "优先级过滤", placeholder: "40,30", hint: "可选。逗号分隔，取值为 10 / 20 / 30 / 40" },
      ],
    },
    {
      path: "/log/list",
      name: "收到的日志",
      action: "查询",
      desc: "读取别人发给你的日报、周报。",
      fields: [],
    },
    {
      path: "/attendance",
      name: "今天的打卡",
      action: "查询",
      desc: "读取今天的考勤打卡流水。",
      fields: [],
    },
    {
      path: "/group/search",
      name: "搜索群聊",
      action: "搜索",
      desc: "按群名找群。发公告前要先在这里拿到群的 openConversationId。",
      fields: [{ name: "query", label: "群名关键词", placeholder: "项目冲刺", required: true }],
    },
  ];

  const WRITE_CARDS = [
    {
      path: "/calendar",
      name: "创建日程",
      action: "创建日程",
      desc: "在钉钉日历上建一条日程，可以邀请参会人。",
      fields: [
        { name: "title", label: "日程标题", placeholder: "项目评审会", required: true },
        { name: "start", label: "开始时间", placeholder: "2026-09-23T14:00:00+08:00", required: true },
        { name: "end", label: "结束时间", placeholder: "2026-09-23T15:00:00+08:00", required: true },
        { name: "attendees", label: "参会人", placeholder: "张三,李四", hint: "可选。逗号分隔姓名，受邀人会收到日程" },
      ],
    },
    {
      path: "/todo",
      name: "创建待办",
      action: "创建待办",
      desc: "给自己记一条待办，可以设截止时间。",
      fields: [
        { name: "task", label: "待办内容", placeholder: "交周报", required: true },
        { name: "at", label: "截止时间", placeholder: "2026-09-25T18:00:00+08:00", hint: "可选，ISO8601 格式" },
      ],
    },
    {
      path: "/todo/assign",
      name: "指派待办",
      action: "指派给同事",
      desc: "把一条待办派给同事，对方会收到通知。",
      fields: [
        { name: "task", label: "待办内容", placeholder: "整理会议纪要", required: true },
        { name: "to", label: "执行人", placeholder: "李四", required: true },
        { name: "due", label: "截止时间", placeholder: "2026-09-26T18:00:00+08:00", hint: "可选" },
      ],
    },
    {
      path: "/message/send",
      name: "发单聊消息",
      action: "发送给这个人",
      desc: "给某位同事发钉钉单聊，对方会收到。收件人和 openDingTalkId 二选一。",
      fields: [
        {
          name: "to",
          label: "收件人姓名",
          placeholder: "张三",
          hint: "同名多人时发不出去，会列出候选，改用下面的 openDingTalkId",
        },
        {
          name: "open_dingtalk_id",
          label: "收件人 openDingTalkId",
          placeholder: "D1bW1rZ5IC2eTed4TfHoxUvRqP5Hk1UP",
          hint: "可选。同名重名时填这个，可先用「搜索联系人」查到",
        },
        { name: "content", label: "消息内容", type: "textarea", required: true, placeholder: "支持 Markdown" },
      ],
    },
    {
      path: "/group-message/send",
      name: "发群消息",
      action: "发送到群里",
      desc: "往群里发一条消息，全体成员都能看到。",
      fields: [
        { name: "group", label: "群名称", placeholder: "项目冲刺", required: true },
        { name: "content", label: "消息内容", type: "textarea", required: true, placeholder: "支持 Markdown" },
      ],
    },
    {
      path: "/ding/send",
      name: "发送 DING",
      action: "发送 DING",
      desc: "强提醒，会响铃甚至打电话。除非确实紧急，否则别用。",
      fields: [
        { name: "users", label: "接收人", placeholder: "openDingTalkId，逗号分隔", required: true },
        { name: "content", label: "提醒内容", type: "textarea", required: true },
        {
          name: "method",
          label: "提醒方式",
          type: "select",
          value: "app",
          options: [
            ["app", "应用内提醒"],
            ["sms", "短信"],
            ["call", "电话"],
          ],
        },
      ],
    },
    {
      path: "/sheet",
      name: "创建在线表格",
      action: "创建表格",
      desc: "新建一篇钉钉在线电子表格。",
      fields: [
        { name: "name", label: "表格名称", placeholder: "Q1 数据", required: true },
        { name: "folder", label: "目标文件夹 ID", hint: "可选" },
        { name: "workspace", label: "目标知识库 ID", hint: "可选" },
      ],
    },
    {
      path: "/log",
      name: "提交日志",
      action: "提交日志",
      desc: "按模板提交日报或周报，接收人会在日志里看到。",
      fields: [
        { name: "template_id", label: "模板 ID", required: true },
        {
          name: "contents",
          label: "内容 JSON",
          type: "textarea",
          required: true,
          placeholder: '[{"key":"今日完成","content":"…"}]',
          hint: "数组，每项含 key / sort / content / contentType / type",
        },
        { name: "to_user_ids", label: "接收人 userId", placeholder: "user1,user2", required: true },
      ],
    },
    {
      path: "/notice",
      name: "发布群公告",
      action: "发布公告",
      desc: "在指定群里发公告，可以置顶，也可以再补一条 DING。",
      fields: [
        {
          name: "conversation_id",
          label: "群 openConversationId",
          placeholder: "cidFQ3a+0mk0am0xbTzkRx2Vg==",
          required: true,
          hint: "先用「搜索群聊」拿到这个值",
        },
        { name: "content", label: "公告正文", type: "textarea", required: true, placeholder: "支持 Markdown" },
        { name: "sticky", label: "置顶这条公告", type: "checkbox" },
        { name: "send_ding", label: "同时发一条 DING 提醒", type: "checkbox" },
      ],
    },
    {
      path: "/robot-message/send",
      name: "发机器人消息",
      action: "让机器人推送",
      desc: "通过群自定义机器人 Webhook 推送消息。",
      fields: [
        {
          name: "content",
          label: "消息内容",
          type: "textarea",
          required: true,
          hint: "需包含机器人安全设置里的关键词，否则会被拒收",
        },
      ],
    },
  ];

  // ---------------- 渲染卡片 ----------------

  function buildField(field) {
    const wrap = document.createElement("label");
    wrap.className = "field";

    if (field.type === "checkbox") {
      wrap.className = "field__row";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.name = field.name;
      const text = document.createElement("span");
      text.textContent = field.label;
      wrap.append(box, text);
      return wrap;
    }

    const label = document.createElement("span");
    label.className = "field__label";
    label.textContent = field.label;
    wrap.append(label);

    let input;
    if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = 3;
    } else if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        input.append(option);
      });
      if (field.value) input.value = field.value;
    } else {
      input = document.createElement("input");
      input.type = "text";
    }

    input.className = "field__input";
    input.name = field.name;
    if (field.placeholder) input.placeholder = field.placeholder;
    if (field.required) input.required = true;
    wrap.append(input);

    if (field.hint) {
      const hint = document.createElement("span");
      hint.className = "field__hint";
      hint.textContent = field.hint;
      wrap.append(hint);
    }
    return wrap;
  }

  function buildCard(spec, isWrite) {
    const card = document.createElement("article");
    card.className = `card${isWrite ? " card--write" : ""}`;

    const head = document.createElement("button");
    head.type = "button";
    head.className = "card__head";
    head.setAttribute("aria-expanded", "false");

    const verb = document.createElement("span");
    verb.className = "card__verb";
    verb.textContent = isWrite ? "POST" : "GET";

    const name = document.createElement("span");
    name.className = "card__name";
    name.textContent = spec.name;

    const chevron = document.createElement("span");
    chevron.className = "card__chevron";
    chevron.textContent = "›";

    head.append(verb, name, chevron);

    const path = document.createElement("p");
    path.className = "card__path";
    path.textContent = `/api/v1/dingtalk${spec.path}`;

    const form = document.createElement("form");
    form.className = "card__form";
    form.hidden = true;

    const describe = document.createElement("p");
    describe.className = "field__hint";
    describe.textContent = spec.desc;
    form.append(describe);

    spec.fields.forEach((field) => form.append(buildField(field)));

    const actions = document.createElement("div");
    actions.className = "card__actions";

    const error = document.createElement("p");
    error.className = "card__error";
    error.hidden = true;

    let confirmBox = null;
    if (isWrite) {
      const confirmWrap = document.createElement("label");
      confirmWrap.className = "card__confirm";
      confirmBox = document.createElement("input");
      confirmBox.type = "checkbox";
      const confirmText = document.createElement("span");
      confirmText.textContent = "我确认执行";
      confirmWrap.append(confirmBox, confirmText);
      actions.append(confirmWrap);
    }

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = `button ${isWrite ? "button--go" : "button--solid"}`;
    submit.textContent = spec.action;
    if (isWrite) submit.disabled = true;
    actions.append(submit);
    form.append(actions, error);

    if (confirmBox) {
      confirmBox.addEventListener("change", () => {
        submit.disabled = !confirmBox.checked;
      });
    }

    head.addEventListener("click", () => {
      const open = form.hidden;
      form.hidden = !open;
      card.classList.toggle("is-open", open);
      head.setAttribute("aria-expanded", String(open));
      if (open) {
        const first = form.querySelector(".field__input");
        if (first) first.focus();
      }
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      runCard(spec, form, isWrite, submit, error);
    });

    card.append(head, path, form);
    return card;
  }

  // ---------------- 调用 ----------------

  function collect(form, spec) {
    const payload = {};
    spec.fields.forEach((field) => {
      const input = form.elements[field.name];
      if (!input) return;
      if (field.type === "checkbox") {
        payload[field.name] = input.checked;
        return;
      }
      const value = input.value.trim();
      if (value !== "") payload[field.name] = value;
    });
    return payload;
  }

  function toQuery(payload) {
    const search = new URLSearchParams();
    Object.entries(payload).forEach(([key, value]) => search.set(key, String(value)));
    const text = search.toString();
    return text ? `?${text}` : "";
  }

  function showDrawer(kind, spec, metaText, content) {
    const verb = document.createElement("span");
    dom.drawerVerb.className = `drawer__verb${kind === "write" ? " drawer__verb--write" : ""}`;
    verb.textContent = kind === "write" ? "POST" : "GET";
    dom.drawerVerb.replaceWith(verb);
    dom.drawerVerb = verb;

    dom.drawerPath.textContent = `/api/v1/dingtalk${spec.path}`;
    dom.drawerMeta.textContent = metaText;
    dom.drawerBody.textContent = content;
    dom.drawer.classList.toggle("drawer--err", metaText.startsWith("失败"));
    dom.drawer.classList.toggle("drawer--ok", !metaText.startsWith("失败"));
    dom.drawer.hidden = false;
  }

  function pretty(payload) {
    let text = JSON.stringify(payload, null, 2);
    if (text === undefined) text = String(payload);
    if (text.length > BODY_LIMIT) text = `${text.slice(0, BODY_LIMIT)}\n…（结果过长，已截断）`;
    return text;
  }

  async function runCard(spec, form, isWrite, submit, error) {
    const payload = collect(form, spec);
    if (isWrite) payload.confirm = true;

    submit.disabled = true;
    error.hidden = true;

    try {
      const result = isWrite
        ? await DT.post(spec.path, payload)
        : await DT.api(`${spec.path}${toQuery(payload)}`);
      showDrawer(isWrite ? "write" : "read", spec, `成功 · ${result.elapsed}ms`, pretty(result.data));
    } catch (failure) {
      const lines = [failure.message];
      if (failure.advice) lines.push("", failure.advice);
      if (failure.detail) lines.push("", `服务返回：${failure.detail}`);
      const text = lines.join("\n");

      error.textContent = failure.message;
      error.hidden = false;
      showDrawer(isWrite ? "write" : "read", spec, `失败 · ${failure.elapsed ?? 0}ms`, text);
    } finally {
      submit.disabled = isWrite;
      if (isWrite) {
        const box = form.querySelector(".card__confirm input");
        if (box) {
          box.checked = false;
          submit.disabled = true;
        }
      }
    }
  }

  // ---------------- 顶部状态条 ----------------

  function setRail(element, text, state) {
    element.textContent = text;
    element.className = "rail__val";
    if (state) element.classList.add(`rail__val--${state}`);
  }

  async function refreshStatus() {
    setRail(dom.railDws, "检查中…", null);
    setRail(dom.railUser, "检查中…", null);

    const status = await DT.loadStatus();
    DT.paintStamp(dom.stamp, status);

    setRail(dom.railDws, status.dwsAvailable ? "可用" : "未就绪", status.dwsAvailable ? "ok" : "off");

    if (!status.dwsAvailable) {
      setRail(dom.railUser, "—", "off");
    } else if (status.authenticated) {
      setRail(dom.railUser, status.user || "已登录", "ok");
    } else {
      setRail(dom.railUser, "未登录", "off");
    }

    if (status.authRaw) {
      dom.railRaw.textContent = pretty(status.authRaw);
    } else if (status.authError) {
      dom.railRaw.textContent = `没有拿到登录状态：${status.authError}`;
    } else {
      dom.railRaw.textContent = "命令行未就绪，暂时读不到登录状态。";
    }
  }

  async function triggerLogin() {
    dom.railLogin.disabled = true;
    try {
      const result = await DT.post("/auth/login", {});
      setRail(dom.railUser, "请在浏览器完成授权", null);
      showDrawer("read", { path: "/auth/login" }, `成功 · ${result.elapsed}ms`, pretty(result.data));
      window.setTimeout(refreshStatus, 4000);
    } catch (failure) {
      showDrawer("read", { path: "/auth/login" }, `失败 · ${failure.elapsed ?? 0}ms`, failure.message);
    } finally {
      dom.railLogin.disabled = false;
    }
  }

  // ---------------- 启动 ----------------

  function init() {
    const readFrag = document.createDocumentFragment();
    READ_CARDS.forEach((spec) => readFrag.append(buildCard(spec, false)));
    dom.readCards.replaceChildren(readFrag);

    const writeFrag = document.createDocumentFragment();
    WRITE_CARDS.forEach((spec) => writeFrag.append(buildCard(spec, true)));
    dom.writeCards.replaceChildren(writeFrag);

    dom.railRefresh.addEventListener("click", refreshStatus);
    dom.railLogin.addEventListener("click", triggerLogin);
    dom.railRawToggle.addEventListener("click", () => {
      const open = dom.railRaw.hidden;
      dom.railRaw.hidden = !open;
      dom.railRawToggle.setAttribute("aria-expanded", String(open));
      dom.railRawToggle.textContent = open ? "收起登录状态原文" : "查看登录状态原文";
    });
    dom.drawerClose.addEventListener("click", () => {
      dom.drawer.hidden = true;
    });

    refreshStatus();
  }

  init();
})();

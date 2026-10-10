/**
 * 钉协助手智能体 · 两个页面共用的工具。
 *
 * 提供：接口调用封装、工具名到中文动作的映射、轻量 Markdown 渲染、
 * 以及两个页面共用的登录/命令行状态检查。
 * 全部挂在 window.DT 上，页面脚本按需取用（不使用模块，方便静态资源带版本号）。
 */
(function () {
  "use strict";

  const API = "/api/v1/dingtalk";

  /**
   * 工具名 -> 中文动作与读写属性。
   * write=false 只读取信息，write=true 会向同事真的发出东西；
   * 这个区别同时决定界面上的措辞与颜色。
   */
  const TOOLS = {
    search_contact: { label: "搜索联系人", write: false },
    list_calendar: { label: "查今天的日程", write: false },
    list_todos: { label: "查我的待办", write: false },
    search_group: { label: "搜索群聊", write: false },
    list_logs: { label: "查收到的日志", write: false },
    get_attendance: { label: "查今天的打卡", write: false },
    create_calendar: { label: "创建日程", write: true },
    create_todo: { label: "创建待办", write: true },
    assign_todo: { label: "给同事指派待办", write: true },
    send_message: { label: "发单聊消息", write: true },
    send_group_message: { label: "发群消息", write: true },
    send_robot_message: { label: "发机器人消息", write: true },
    publish_notice: { label: "发布群公告", write: true },
    send_ding: { label: "发送 DING 强提醒", write: true },
    create_sheet: { label: "创建在线表格", write: true },
    create_log: { label: "提交日志", write: true },
  };

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** 行内标记：先转义再解析 ``**加粗**`` 与反引号代码。 */
  function inlineMarkup(text) {
    return text
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  /** 轻量 Markdown：段落、有序/无序列表、加粗与行内代码，渲染前统一转义。 */
  function formatRich(text) {
    const lines = escapeHtml(text).split(/\r?\n/);
    const out = [];
    let paragraph = [];
    let list = null;

    function flushParagraph() {
      if (paragraph.length) {
        out.push(`<p>${inlineMarkup(paragraph.join("<br>"))}</p>`);
        paragraph = [];
      }
    }

    function flushList() {
      if (list) {
        out.push(`</${list}>`);
        list = null;
      }
    }

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        flushList();
        return;
      }
      const bullet = /^[-*·]\s+(.*)$/.exec(trimmed);
      const ordered = /^(\d+)[.、)]\s+(.*)$/.exec(trimmed);
      const heading = /^#{1,4}\s+(.*)$/.exec(trimmed);

      if (bullet) {
        flushParagraph();
        if (list !== "ul") {
          flushList();
          out.push("<ul>");
          list = "ul";
        }
        out.push(`<li>${inlineMarkup(bullet[1])}</li>`);
      } else if (ordered) {
        flushParagraph();
        if (list !== "ol") {
          flushList();
          out.push("<ol>");
          list = "ol";
        }
        out.push(`<li>${inlineMarkup(ordered[2])}</li>`);
      } else if (heading) {
        flushParagraph();
        flushList();
        out.push(`<p><strong>${inlineMarkup(heading[1])}</strong></p>`);
      } else {
        flushList();
        paragraph.push(trimmed);
      }
    });

    flushParagraph();
    flushList();
    return out.join("");
  }

  /** 把工具入参压成一行可读文本，例如 ``city=杭州 · days=3``。 */
  function argsText(args) {
    if (!args || typeof args !== "object") return "";
    const parts = [];
    Object.entries(args).forEach(([key, value]) => {
      if (value === null || value === undefined || value === "" || value === false) return;
      const shown = typeof value === "object" ? JSON.stringify(value) : String(value);
      parts.push(`${key}=${shown}`);
    });
    return parts.join(" · ");
  }

  /**
   * 失败原因优先照搬服务端给的话。
   *
   * 钉钉 CLI 的失败（没装 dws、没登录、写开关没开、dws 退出码非零）
   * 都由后端带中文说明返回，直接展示那条说明最有用；只有在拿不到说明时
   * 才退回通用引导。
   */
  function describeFailure(status, detail) {
    const raw = (detail || "").trim();

    if (status === 422) {
      return { message: "提交的参数不合法。", advice: "检查必填项和格式后重试。", detail: raw };
    }
    if (status === 404) {
      return { message: "接口不存在，可能服务跑的是旧版本。", advice: "重启服务后再试。", detail: raw };
    }
    if (raw && raw !== "Internal Server Error") {
      return { message: raw, advice: "", detail: "" };
    }
    if (status >= 500) {
      return {
        message: "服务端出错了，但没带回具体原因。",
        advice: "到服务端查看 src/app/logs/app.log 里的堆栈，确认后再试。",
        detail: raw,
      };
    }
    return {
      message: `请求失败（HTTP ${status}）。`,
      advice: "确认服务仍在运行后重试。",
      detail: raw,
    };
  }

  /**
   * 调用钉钉接口。
   * 成功返回 ``{data, elapsed, status}``；失败抛出带 ``status``/``elapsed``/``raw`` 的 Error。
   */
  async function api(path, options) {
    const started = performance.now();
    let response;
    try {
      response = await fetch(API + path, { cache: "no-store", ...(options || {}) });
    } catch (cause) {
      const error = new Error("连不上服务，请确认后端仍在运行。");
      error.status = 0;
      error.elapsed = Math.round(performance.now() - started);
      error.cause = cause;
      throw error;
    }
    const elapsed = Math.round(performance.now() - started);
    const text = await response.text();

    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }

    if (!response.ok) {
      let detail = text;
      if (data && data.detail !== undefined) {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
      const info = describeFailure(response.status, detail);
      const error = new Error(info.message);
      error.status = response.status;
      error.elapsed = elapsed;
      error.advice = info.advice;
      error.detail = info.detail;
      throw error;
    }

    return { data, elapsed, status: response.status };
  }

  /** POST JSON 的语法糖。 */
  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  /** 从 auth status 的各种可能字段里认出「是否已登录」和「叫什么」。 */
  function readAuth(payload) {
    const value = payload && typeof payload === "object" ? payload : {};
    const nested = value.data && typeof value.data === "object" ? value.data : value;
    const authenticated = Boolean(
      nested.authenticated ?? nested.isAuthenticated ?? nested.logged_in ?? nested.loggedIn ?? false,
    );
    const name = nested.user_name || nested.userName || nested.nickname || nested.name || nested.userId || "";
    return { authenticated, name: String(name || "") };
  }

  /**
   * 两个页面共用的状态检查：命令行是否可用、当前登录的是谁。
   * 任何一步失败都不抛出，交给调用方决定怎么显示。
   */
  async function loadStatus() {
    const result = { dwsAvailable: false, authenticated: false, user: "", authRaw: null, authError: "" };

    try {
      const health = await api("/health");
      result.dwsAvailable = Boolean(health.data && health.data.dws_available);
    } catch (error) {
      result.authError = error.message;
      return result;
    }

    if (!result.dwsAvailable) return result;

    try {
      const auth = await api("/auth/status");
      result.authRaw = auth.data;
      const parsed = readAuth(auth.data);
      result.authenticated = parsed.authenticated;
      result.user = parsed.name;
    } catch (error) {
      result.authError = error.message;
    }
    return result;
  }

  /** 渲染报头右侧的状态文字。 */
  function paintStamp(element, status) {
    if (!element) return;
    element.classList.remove("stamp--ok", "stamp--off");
    if (!status.dwsAvailable) {
      element.classList.add("stamp--off");
      element.innerHTML = '<span class="stamp__dot"></span>钉钉命令行未就绪';
      return;
    }
    if (status.authenticated) {
      element.classList.add("stamp--ok");
      const who = status.user ? ` · ${escapeHtml(status.user)}` : "";
      element.innerHTML = `<span class="stamp__dot"></span>已登录${who}`;
      return;
    }
    element.classList.add("stamp--off");
    element.innerHTML = '<span class="stamp__dot"></span>还没登录钉钉';
  }

  window.DT = {
    API,
    TOOLS,
    escapeHtml,
    formatRich,
    argsText,
    api,
    post,
    loadStatus,
    paintStamp,
  };
})();

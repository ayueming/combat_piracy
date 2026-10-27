# link_picker_injector.py

PICKER_JS = r"""
(function () {
  if (window.__aptPickerInjected && document.getElementById("__apt_picker_host__")) return;
  window.__aptPickerInjected = true;

  const HOST_ID = "__apt_picker_host__";
  const state = { picking: false, ctx: null, hoverEl: null, savedCount: 0 };
  let host, shadow, overlay, mask, toastEl, statusEl, btnPick, btnSave, btnClose, ctxBox;
  let navBar, navPrev, navNext, navLabel;

  // ===== 历史栈：用于同 Tab 溯源 =====
  let navHistory = [];
  try {
      const saved = sessionStorage.getItem("__aptNavHistory");
      if (saved) navHistory = JSON.parse(saved);
  } catch(e) {}

  const curPage = { url: location.href, title: document.title || "" };
  if (navHistory.length === 0 || navHistory[navHistory.length - 1].url !== curPage.url) {
      navHistory.push(curPage);
      if (navHistory.length > 10) navHistory.shift();
      try { sessionStorage.setItem("__aptNavHistory", JSON.stringify(navHistory)); } catch(e) {}
  }

  function buildDom() {
    const oldHost = document.getElementById(HOST_ID);
    if (oldHost) oldHost.remove();

    try {
      host = document.createElement("div");
      host.id = HOST_ID;
      host.style.cssText = "all: initial; position:fixed !important; right:20px !important; bottom:20px !important; z-index:2147483647 !important; font-family:Microsoft YaHei,Arial,sans-serif !important;";

      const parent = document.body || document.documentElement;
      if (!parent) { setTimeout(buildDom, 50); return; }
      parent.appendChild(host);

      shadow = host.attachShadow({ mode: "closed" });
      const style = document.createElement("style");
      style.textContent = `
        :host, * { box-sizing: border-box; }
        .panel { width: 220px; background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,.12); font-size: 12px; color: #24292f; overflow: hidden; pointer-events: auto !important; }
        .head { background: #f6f8fa; padding: 8px 10px; font-weight: 600; border-bottom: 1px solid #eaeef2; display: flex; justify-content: space-between; align-items: center; }

        .nav-bar { display: none; background: #EFF6FF; border-bottom: 1px solid #BFDBFE; padding: 6px; align-items: center; justify-content: space-between; }
        .nav-bar button { background: #3B82F6; color: white; border: none; border-radius: 4px; padding: 4px 8px; width: auto; font-size: 12px; }
        .nav-bar button:hover { background: #2563EB; }
        .nav-bar button:disabled { background: #93C5FD; cursor: not-allowed; }
        .nav-label { font-weight: bold; color: #1E3A8A; font-size: 12px; }

        .ctx { padding: 8px 10px; border-bottom: 1px solid #eaeef2; }
        .ctx div { margin-bottom: 3px; color: #57606a; word-break: break-all; }
        .ctx b { color: #24292f; font-weight: 600; }
        .actions { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; }
        button { padding: 6px 0; border-radius: 5px; cursor: pointer !important; font-size: 12px; font-weight: 600; border: 1px solid transparent; font-family: inherit; pointer-events: auto !important; }
        .btn-save { background: #1f6feb; color: #fff; }
        .btn-save:hover { background: #1a5fd0; }
        .btn-pick { background: #f6f8fa; color: #24292f; border-color: #d0d7de; }
        .btn-pick:hover { background: #eaeef2; }
        .btn-pick.active { background: #fff8c5; border-color: #d4a72c; color: #7d4e00; }
        .btn-close { background: #10B981; color: #fff; margin-top: 4px; }
        .btn-close:hover { background: #059669; }
        .status { padding: 6px 10px; background: #f6f8fa; color: #57606a; font-size: 11px; }
      `;
      shadow.appendChild(style);

      const panel = document.createElement("div");
      panel.className = "panel";

      const head = document.createElement("div");
      head.className = "head";
      head.textContent = "反盗版助手";
      panel.appendChild(head);

      navBar = document.createElement("div");
      navBar.className = "nav-bar";
      navPrev = document.createElement("button");
      navPrev.textContent = "⬅️ 上一个";
      navPrev.onclick = () => triggerNav("prev");
      navLabel = document.createElement("span");
      navLabel.className = "nav-label";
      navLabel.textContent = "1 / 1";
      navNext = document.createElement("button");
      navNext.textContent = "下一个 ➡️";
      navNext.onclick = () => triggerNav("next");
      navBar.appendChild(navPrev);
      navBar.appendChild(navLabel);
      navBar.appendChild(navNext);
      panel.appendChild(navBar);

      const ctxDiv = document.createElement("div");
      ctxDiv.className = "ctx";
      const divBook = document.createElement("div"); divBook.textContent = "作品："; const bBook = document.createElement("b"); bBook.className = "v-book"; bBook.textContent = "-"; divBook.appendChild(bBook); ctxDiv.appendChild(divBook);
      const divKw = document.createElement("div"); divKw.textContent = "关键词："; const bKw = document.createElement("b"); bKw.className = "v-kw"; bKw.textContent = "-"; divKw.appendChild(bKw); ctxDiv.appendChild(divKw);
      panel.appendChild(ctxDiv);

      const actions = document.createElement("div");
      actions.className = "actions";

      btnSave = document.createElement("button");
      btnSave.className = "btn-save";
      btnSave.textContent = "仅保存当前网址";
      actions.appendChild(btnSave);

      btnPick = document.createElement("button");
      btnPick.className = "btn-pick";
      btnPick.textContent = "手动拾取链接（或按住ALT）";
      actions.appendChild(btnPick);

      btnClose = document.createElement("button");
      btnClose.className = "btn-close";
      btnClose.textContent = "💾 保存本批";
      actions.appendChild(btnClose);

      panel.appendChild(actions);
      const statusDiv = document.createElement("div"); statusDiv.className = "status"; statusDiv.textContent = "待保存 "; statusEl = document.createElement("b"); statusEl.className = "v-count"; statusEl.textContent = "0"; statusDiv.appendChild(statusEl); statusDiv.appendChild(document.createTextNode(" 条")); panel.appendChild(statusDiv);
      shadow.appendChild(panel);

      ctxBox = { book: bBook, kw: bKw };

      overlay = document.createElement("div");
      overlay.style.cssText = "all: initial; position:fixed; pointer-events:none; border:2px solid #1f6feb; background:rgba(31,111,235,.12); border-radius:3px; display:none; z-index:2147483646; transition:all .08s ease;";
      document.body.appendChild(overlay);

      mask = document.createElement("div");
      mask.style.cssText = "all: initial; position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:2147483645; background:transparent; display:none; cursor:crosshair;";
      document.body.appendChild(mask);

      toastEl = document.createElement("div");
      toastEl.style.cssText = "all: initial; position:fixed; right:20px; bottom:180px; z-index:2147483647; padding:8px 12px; background:rgba(0,0,0,.82); color:#fff; border-radius:6px; font-size:12px; display:none; max-width:260px; font-family:Microsoft YaHei,Arial,sans-serif;";
      document.body.appendChild(toastEl);

      btnSave.addEventListener("click", onSavePage);
      btnPick.addEventListener("click", togglePicking);
      btnClose.addEventListener("click", onSaveBatch);

      mask.addEventListener("mousemove", onMaskMouseMove, true);
      mask.addEventListener("mousedown", onMaskMouseDown, true);
    } catch (e) { console.error("[apt-picker] DOM build fail:", e); }
  }

  // ===== 暴露给外部的 API =====
  window.__aptUpdateSavedCount = function (n) {
      state.savedCount = (typeof n === "number" && n >= 0) ? n : 0;
      if (statusEl) statusEl.textContent = String(state.savedCount);
      try { sessionStorage.setItem("__aptSavedCount", String(state.savedCount)); } catch(e) {}
  };

  window.__aptEnterPicking = function () { if (!state.picking) enterPicking(); };
  window.__aptExitPicking  = function () { if (state.picking)  exitPicking(); };

  // ===== Alt 瞬态拾取逻辑 =====
  const ALT_HOLD_MS = 120;
  let _altHoldTimer = null;
  let _altActive = false;

  function _resetAltHold() {
      if (_altHoldTimer) { clearTimeout(_altHoldTimer); _altHoldTimer = null; }
      if (_altActive) {
          _altActive = false;
          if (state.picking) exitPicking();
      }
  }

  document.addEventListener("keydown", function (e) {
      // 组合键打断取消
      if (_altHoldTimer && e.key !== "Alt") {
          clearTimeout(_altHoldTimer);
          _altHoldTimer = null;
      }

      if (e.key !== "Alt") return;
      if (e.repeat) return;
      if (isEditable(e.target)) return;
      if (_altActive || _altHoldTimer) return;

      _altHoldTimer = setTimeout(() => {
          _altHoldTimer = null;
          _altActive = true;
          if (!state.picking) enterPicking("alt_hold");
      }, ALT_HOLD_MS);
  }, true);

  document.addEventListener("keyup", function (e) {
      if (e.key !== "Alt") return;
      _resetAltHold();
  }, true);

  // ★ 防焦点丢失卡死
  window.addEventListener("blur", _resetAltHold);
  document.addEventListener("visibilitychange", function () {
      if (document.hidden) _resetAltHold();
  });

  // 保留 ESC 退出
  document.addEventListener("keydown", function(e) {
      if (e.key === "Escape" && state.picking) { exitPicking(); e.preventDefault(); }
  }, true);


  function renderCtx() {
    if (!ctxBox) return;
    const c = state.ctx || {};
    ctxBox.book.textContent = c.book_name || "-";
    ctxBox.kw.textContent = c.keyword || "-";

    if (c.batch_total && c.batch_total > 1) {
        navBar.style.display = "flex";
        navLabel.textContent = `${c.batch_index} / ${c.batch_total}`;
        navPrev.disabled = c.batch_index <= 1;
        navNext.disabled = c.batch_index >= c.batch_total;
    } else {
        navBar.style.display = "none";
    }
  }

  function showToast(msg, ms) {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.style.display = "block";
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => { toastEl.style.display = "none"; }, ms || 2500);
  }

  function batchPushToQueue(rawLinks, actionType) {
    if (!rawLinks || rawLinks.length === 0) return 0;
    let uniqueLinks = []; let seen = new Set();
    rawLinks.forEach(l => {
        if (!l.url || !/^https?:/i.test(l.url)) return;
        if (!seen.has(l.url)) { seen.add(l.url); uniqueLinks.push(l); }
    });
    if (uniqueLinks.length === 0) return 0;
    if (!window.__aptSaveQueue) window.__aptSaveQueue = [];
    uniqueLinks.forEach(l => {
        window.__aptSaveQueue.push({
            action: actionType,
            url: l.url,
            title: (l.title || "").trim().slice(0, 200),
            body: (l.body || "").trim(),
            source_site: (l.source_site || "").trim(),
            parent_url: (l.parent_url || "").trim(),
            parent_title: (l.parent_title || "").trim(),
            pan_url: (l.pan_url || "").trim(),
            ctx: state.ctx || {}
        });
    });
    return uniqueLinks.length;
  }

  function triggerNav(direction) {
    if (!window.__aptSaveQueue) window.__aptSaveQueue = [];
    window.__aptSaveQueue.push({ action: "preview_nav", url: direction, title: "", ctx: state.ctx || {} });
    showToast(direction === "next" ? "正在切到下一个..." : "正在切到上一个...");
  }

  function onSavePage(e) {
    e.preventDefault(); e.stopPropagation();
    batchPushToQueue([{ url: location.href, title: document.title }], "save_page");
    showToast("已保存当前页面");
  }

  function onSaveBatch(e) {
    e.preventDefault(); e.stopPropagation();
    if (!window.__aptSaveQueue) window.__aptSaveQueue = [];
    window.__aptSaveQueue.push({ action: "save_batch", url: "", title: "", ctx: state.ctx || {} });
    showToast("正在保存本批...");
  }

  // =========================================================================
  // ★ 百度搜索扫描
  // =========================================================================
  window.__aptAutoScan = function () {
    let rawLinks = [];
    document.querySelectorAll('#content_left a, h3 a, .result a, .cosc-title-a').forEach(a => {
        let realUrl = a.getAttribute('data-landurl') || a.href;
        let title = (a.innerText || "").trim();
        if (realUrl.includes('hao123.com') || realUrl === 'http://www.baidu.com/') return;
        if (realUrl.includes('baidu.com') && !realUrl.includes('link?url=')) return;

        let container = a.closest('.c-container') || a.closest('.result') || a.closest('div');
        let bodyText = "";
        let sourceSite = "";

        if (container) {
            let bodyEl = container.querySelector('[data-module="abstract"] .summary-text_15QGa')
                       || container.querySelector('[data-module="abstract"]')
                       || container.querySelector('.c-abstract')
                       || container.querySelector('.c-span-last');
            if (bodyEl && bodyEl.innerText) {
                bodyText = bodyEl.innerText.trim();
            }

            let srcEl = container.querySelector('[data-module="source"] .cosc-source-text');
            if (srcEl && srcEl.innerText) {
                sourceSite = srcEl.innerText.trim();
            } else {
                let grayEls = container.querySelectorAll('.c-color-gray, .c-showurl, .g, .c-color-text');
                for (let el of grayEls) {
                    if (el && el.innerText) {
                        let txt = el.innerText.trim();
                        if (txt.length > 0 && txt.length < 30 && !txt.includes('百度')) {
                            if (txt.length > sourceSite.length) {
                                sourceSite = txt;
                            }
                        }
                    }
                }
            }
        }

        if (title.length > 4) {
            rawLinks.push({ url: realUrl, title: title, body: bodyText, source_site: sourceSite });
        }
    });
    return batchPushToQueue(rawLinks, "pick_link");
  };

  // =========================================================================
  // ★ 夸克搜索专属扫描
  // =========================================================================
  window.__aptAutoScan_quark = function () {
    let rawLinks = [];
    document.querySelectorAll('.qk-card').forEach(card => {
        if (card.dataset.aptScanned === "1") return;

        let titleEl = card.querySelector('.qk-title-content a');
        let bodyEl = card.querySelector('.qk-paragraph-text');
        let sourceEl = card.querySelector('.qk-source-item');

        if (!titleEl || !titleEl.href) return;

        let realUrl = titleEl.href;
        let title = (titleEl.innerText || "").trim();
        let bodyText = bodyEl ? (bodyEl.innerText || "").trim() : "";
        let sourceSite = sourceEl ? (sourceEl.innerText || "").trim() : "";

        if (realUrl.includes('quark.cn/s')) return;

        if (title.length > 2) {
            rawLinks.push({
                url: realUrl,
                title: title,
                body: bodyText,
                source_site: sourceSite
            });
            card.dataset.aptScanned = "1";
        }
    });

    return batchPushToQueue(rawLinks, "pick_link");
  };

  // =========================================================================
  // ★ 百度知道专属扫描
  // =========================================================================
  window.__aptAutoScan_zhidao = function () {
    let rawLinks = [];
    document.querySelectorAll('dl.dl').forEach(card => {
        if (card.dataset.aptScanned === "1") return;

        let titleEl = card.querySelector('dt.dt a.ti');
        if (!titleEl || !titleEl.href) return;

        let realUrl = titleEl.href;
        if (!realUrl.includes('zhidao.baidu.com/question/')) return;

        let title = (titleEl.innerText || "").trim();
        if (!title) return;

        let bodyEl = card.querySelector('dd.answer');
        let bodyText = bodyEl ? (bodyEl.innerText || "").trim() : "";
        if (bodyText.startsWith("答：")) {
            bodyText = bodyText.substring(2).trim();
        }

        let sourceSite = "百度知道";
        let authorEl = card.querySelector('dd.explain a.f-lighter');
        if (authorEl && authorEl.innerText) {
            sourceSite = authorEl.innerText.trim();
        }

        if (title.length > 2) {
            rawLinks.push({
                url: realUrl,
                title: title,
                body: bodyText,
                source_site: sourceSite
            });
            card.dataset.aptScanned = "1";
        }
    });

    return batchPushToQueue(rawLinks, "pick_link");
  };

  // =========================================================================
  // ★ 百度贴吧专属扫描
  // =========================================================================
  window.__aptAutoScan_tieba = function () {
    let rawLinks = [];
    const cardRoots = document.querySelectorAll('.virtual-list-item, .threadcardclass.index-feed-cards');
    const seenPostIds = new Set();

    cardRoots.forEach(root => {
        const threadCard = root.classList.contains('threadcardclass')
            ? root
            : root.querySelector('.threadcardclass');
        if (!threadCard) return;
        if (threadCard.dataset.aptScanned === "1") return;

        const dataKeyHost = threadCard.closest('[data-key]');
        const postId = dataKeyHost ? dataKeyHost.getAttribute('data-key') : '';
        if (postId && seenPostIds.has(postId)) return;

        let title = threadCard.getAttribute('title') || '';
        if (!title) {
            const titleEl = threadCard.querySelector('.title-wrap span');
            if (titleEl) title = (titleEl.innerText || '').trim();
        }
        if (!title) return;

        let postUrl = '';
        const postLink = threadCard.querySelector('a[href*="/p/"]');
        if (postLink && postLink.href) {
            postUrl = postLink.href;
        }
        if (!postUrl && postId) {
            postUrl = `https://tieba.baidu.com/p/${postId}`;
        }
        try {
            const u = new URL(postUrl);
            postUrl = `${u.origin}${u.pathname}`;
        } catch (e) {}
        if (!postUrl) return;

        const bodyEl = threadCard.querySelector('.abstract-wrap span, .abstract-wrap');
        let bodyText = bodyEl ? (bodyEl.innerText || "").trim() : "";

        const forumEl = threadCard.querySelector('.forum-name-text');
        let sourceSite = forumEl ? (forumEl.innerText || "").trim() : "百度贴吧";

        const cleanSearchText = (title + bodyText).replace(/\s+/g, '');
        const panMatch = cleanSearchText.match(
            /https?:\/\/pan\.baidu\.com\/(?:s\/|share\/init\?surl=)[a-zA-Z0-9_\-]+(?:\?[a-zA-Z0-9_\-=&%]*)?/
        );
        let panUrl = panMatch ? panMatch[0] : "";
        if (panUrl.includes('/share/init?surl=')) {
            panUrl = panUrl.replace('/share/init?surl=', '/s/1');
        }

        if (postId) seenPostIds.add(postId);
        threadCard.dataset.aptScanned = "1";

        rawLinks.push({
            url: postUrl,
            title: title,
            body: bodyText,
            source_site: sourceSite,
            parent_url: "",
            parent_title: "",
            pan_url: panUrl
        });
    });

    return batchPushToQueue(rawLinks, "pick_link");
  };

  function togglePicking(e) {
    e.preventDefault(); e.stopPropagation();
    if (state.picking) exitPicking(); else enterPicking();
  }

  function enterPicking(source) {
    state.picking = true; sessionStorage.setItem("__aptPickingMode", "1");
    if (btnPick) { btnPick.classList.add("active"); btnPick.textContent = "🔴 拾取中（点击退出）"; }
    if (mask) mask.style.display = "block";
    if (host) host.style.borderLeft = "4px solid #EF4444"; // 提示状态

    if (source === "alt_hold") {
        showToast("🖱 按住 Alt 拾取中，松开退出", 1500);
    } else {
        showToast("遮罩已开启，点击链接拾取。ESC 退出", 3000);
    }
  }

  function exitPicking() {
    state.picking = false; sessionStorage.removeItem("__aptPickingMode");
    if (btnPick) { btnPick.classList.remove("active"); btnPick.textContent = "手动拾取链接（或按住ALT）"; }
    if (mask) mask.style.display = "none";
    if (overlay) overlay.style.display = "none";
    if (host) host.style.borderLeft = ""; // 清除状态
    state.hoverEl = null;
    showToast("已退出拾取模式", 1500);
  }

  function isEditable(el) { const t = el.tagName; return t === "INPUT" || t === "TEXTAREA" || el.isContentEditable; }

  function findLink(el) {
    let cur = el;
    while (cur && cur !== document.documentElement) {
        if (cur.tagName === "A" && cur.href) return cur;
        cur = cur.parentElement;
    }

    let txt = (el.innerText || el.textContent || "").trim();
    if (/https?:\/\//.test(txt)) {
        return el;
    }

    if (location.hostname === "tieba.baidu.com") {
        const card = el.closest(".threadcardclass.index-feed-cards");
        if (card) {
            const postLink = card.querySelector("a[href*='/p/']");
            if (postLink) return postLink;
        }
    }
    return null;
  }

  function onMaskMouseMove(e) {
    if (!state.picking || !overlay) return;
    mask.style.pointerEvents = "none";
    const realTarget = document.elementFromPoint(e.clientX, e.clientY);
    mask.style.pointerEvents = "auto";
    if (!realTarget) { overlay.style.display = "none"; return; }

    const link = findLink(realTarget);
    if (!link) { overlay.style.display = "none"; state.hoverEl = null; return; }

    if (link !== state.hoverEl) {
        state.hoverEl = link;
        const r = link.getBoundingClientRect();
        overlay.style.left = r.left + "px"; overlay.style.top = r.top + "px";
        overlay.style.width = r.width + "px"; overlay.style.height = r.height + "px";
        overlay.style.display = "block";
    }
  }

  function onMaskMouseDown(e) {
    if (!state.picking) return;
    mask.style.pointerEvents = "none";
    const realTarget = document.elementFromPoint(e.clientX, e.clientY);
    mask.style.pointerEvents = "auto";
    if (!realTarget) return;

    const link = findLink(realTarget);
    if (link) {
        e.preventDefault(); e.stopPropagation();

        let finalUrl = link.href || "";
        let titleText = (link.innerText || link.textContent || "").trim() || "未命名链接";

        if (!finalUrl) {
            let cleanText = titleText.replace(/\s+/g, '');
            let match = cleanText.match(/https?:\/\/[a-zA-Z0-9\-\._~:\/?#\[\]@!\$&'\(\)\*\+,;=%]+/);
            if (match) {
                finalUrl = match[0];
                titleText = "文本提取: " + finalUrl;
            }
        }

        if (!finalUrl) {
            showToast("未检测到有效链接");
            return;
        }

        // ★ 溯源优先级判断
        let p_url = "";
        let p_title = "";
        const ctx = state.ctx || {};

        if (ctx._opener_url) {
            p_url = ctx._opener_url;
            p_title = ctx._opener_title;
        } else {
            let parentNode = navHistory.length >= 2 ? navHistory[navHistory.length - 2] : null;
            if (parentNode) {
                p_url = parentNode.url;
                p_title = parentNode.title;
            } else {
                p_url = window.location.href;
                p_title = document.title || "";
            }
        }

        batchPushToQueue([{
            url: finalUrl,
            title: titleText,
            parent_url: p_url,
            parent_title: p_title
        }], "pick_link");
        showToast("已拾取链接");
    }
  }

  window.__aptUpdateCtx = function (ctx) {
    state.ctx = ctx || null;
    try { if (ctx) sessionStorage.setItem("__aptCtx", JSON.stringify(ctx)); else sessionStorage.removeItem("__aptCtx"); } catch(e){}
    renderCtx();
  };

  function init() {
    if (!document.body) { setTimeout(init, 50); return; }
    buildDom();

    try {
      const savedCtx = sessionStorage.getItem("__aptCtx");
      if (savedCtx) state.ctx = JSON.parse(savedCtx);

      const savedCount = parseInt(sessionStorage.getItem("__aptSavedCount") || "0", 10);
      if (Number.isFinite(savedCount) && savedCount > 0) state.savedCount = savedCount;

      if (statusEl) statusEl.textContent = String(state.savedCount);

      if (sessionStorage.getItem("__aptPickingMode") === "1") enterPicking();
    } catch(e){}

    renderCtx();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
"""


def get_picker_script():
    return PICKER_JS
const toast = document.querySelector("#toast");

function notify(message, isError = false) {
  toast.textContent = message;
  toast.className = isError ? "show error" : "show";
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => { toast.className = ""; }, 4200);
}

const sourceFetchNotice = window.sessionStorage.getItem("w1ndvoice.sourceFetchNotice");
if (sourceFetchNotice) {
  window.sessionStorage.removeItem("w1ndvoice.sourceFetchNotice");
  notify(sourceFetchNotice, true);
}

async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch (_) {
    throw new Error("无法连接 W1ndVoice 后端，请确认本地服务正在运行");
  }
  let data = {};
  try { data = await response.json(); } catch (_) { /* no JSON body */ }
  if (!response.ok) throw new Error(formatApiError(data.detail, response.status));
  return data;
}

function formatApiError(detail, status) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.at(-1) : "输入内容";
      return `${location}: ${item.msg || "格式不正确"}`;
    }).join("；");
  }
  if (detail && typeof detail === "object") {
    try { return JSON.stringify(detail); } catch (_) { /* use fallback */ }
  }
  return `请求失败 (${status})`;
}

function buttonBusy(button, busy, text = "处理中…") {
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = text;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function leaveSourceEditMode(form) {
  form.reset();
  delete form.dataset.editId;
  delete form.dataset.originalName;
  updateFetchIntervalVisibility(form);
  updateSourceKindVisibility(form);
  document.querySelector("#save-source").textContent = "仅添加";
  document.querySelector("#save-fetch-source").textContent = "添加并立即抓取";
  document.querySelector("#cancel-edit").classList.add("hidden");
}

function updateFetchIntervalVisibility(form) {
  const neverAutoFetch = form.elements.never_auto_fetch.checked;
  document.querySelector("#fetch-interval-field").classList.toggle("hidden", neverAutoFetch);
}

function updateSourceKindVisibility(form) {
  const usesWebOptions = ["auto", "web"].includes(form.elements.kind.value);
  document.querySelector("#max-pages-field").classList.toggle("hidden", !usesWebOptions);
  document.querySelector("#item-selector-field").classList.toggle("hidden", !usesWebOptions);
}

document.querySelector("#source-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = event.submitter || form.querySelector("button[type=submit]");
  const fetchNow = button.dataset.action === "fetch";
  const editId = form.dataset.editId;
  const values = Object.fromEntries(new FormData(form));
  values.name = values.name.trim();
  values.category = values.category.trim();
  const nameChanged = !editId ||
    values.name.toLocaleLowerCase() !== (form.dataset.originalName || "").trim().toLocaleLowerCase();
  const duplicateName = nameChanged && [...document.querySelectorAll(".edit-source")].some((sourceButton) =>
    sourceButton.dataset.id !== editId &&
    sourceButton.dataset.name.trim().toLocaleLowerCase() === values.name.toLocaleLowerCase()
  );
  if (duplicateName) {
    notify("信息源名称已存在，请使用不同名称", true);
    form.elements.name.focus();
    return;
  }
  if (!values.name || !values.category) {
    notify("信息源名称和分类不能为空", true);
    return;
  }
  values.fetch_interval_hours = Number(values.fetch_interval_hours);
  values.max_pages = Number(values.max_pages);
  values.auto_fetch_enabled = values.never_auto_fetch !== "on";
  delete values.never_auto_fetch;
  values.auto_analyze = values.auto_analyze === "on";
  values.enabled = true;
  const busyText = editId
    ? (fetchNow ? "正在保存并抓取…" : "正在保存…")
    : (fetchNow ? "正在添加并抓取…" : "正在添加…");
  buttonBusy(button, true, busyText);
  try {
    const source = await api(editId ? `/api/sources/${editId}` : "/api/sources", {
      method: editId ? "PUT" : "POST",
      body: JSON.stringify(values),
    });
    if (fetchNow) {
      try {
        const result = await api(`/api/sources/${source.id}/fetch`, { method: "POST" });
        notify(`抓取完成，新增或更新 ${result.changed} 条`);
      } catch (error) {
        const saved = editId ? "信息源修改已保存" : "信息源已添加";
        window.sessionStorage.setItem(
          "w1ndvoice.sourceFetchNotice",
          `${saved}，但抓取失败：${error.message}。请在信息源列表点击“立即抓取”重试。`
        );
        location.reload();
        return;
      }
    } else {
      notify(editId ? "信息源修改已保存" : "信息源已添加");
    }
    window.setTimeout(() => location.reload(), 450);
  } catch (error) {
    notify(error.message, true);
    buttonBusy(button, false);
  }
});

document.querySelectorAll(".edit-source").forEach((button) => {
  button.addEventListener("click", () => {
    const form = document.querySelector("#source-form");
    form.dataset.editId = button.dataset.id;
    form.dataset.originalName = button.dataset.name;
    form.elements.name.value = button.dataset.name;
    form.elements.url.value = button.dataset.url;
    form.elements.category.value = button.dataset.category;
    form.elements.kind.value = button.dataset.kind;
    updateSourceKindVisibility(form);
    form.elements.item_selector.value = button.dataset.selector;
    form.elements.fetch_interval_hours.value = button.dataset.hours;
    form.elements.max_pages.value = button.dataset.pages;
    form.elements.never_auto_fetch.checked = button.dataset.autoFetch === "0";
    updateFetchIntervalVisibility(form);
    form.elements.auto_analyze.checked = button.dataset.auto === "1";
    form.elements.ai_prompt.value = button.dataset.prompt;
    document.querySelector("#save-source").textContent = "保存修改";
    document.querySelector("#save-fetch-source").textContent = "保存并立即抓取";
    document.querySelector("#cancel-edit").classList.remove("hidden");
    form.closest("details").open = true;
    form.scrollIntoView({ behavior: "smooth", block: "start" });
    form.elements.name.focus({ preventScroll: true });
  });
});

document.querySelector("#cancel-edit")?.addEventListener("click", () => {
  leaveSourceEditMode(document.querySelector("#source-form"));
});

const sourceForm = document.querySelector("#source-form");
sourceForm?.elements.never_auto_fetch.addEventListener("change", (event) => {
  updateFetchIntervalVisibility(event.target.form);
});
sourceForm?.elements.kind.addEventListener("change", (event) => {
  updateSourceKindVisibility(event.target.form);
});
if (sourceForm) {
  updateFetchIntervalVisibility(sourceForm);
  updateSourceKindVisibility(sourceForm);
}

document.querySelector("#ai-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const values = Object.fromEntries(new FormData(form));
  buttonBusy(button, true, "正在保存…");
  try {
    await api("/api/settings/ai", { method: "PUT", body: JSON.stringify(values) });
    form.api_key.value = "";
    notify("AI 设置已安全保存");
  } catch (error) {
    notify(error.message, true);
  } finally {
    buttonBusy(button, false);
  }
});

document.querySelector("#server-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  buttonBusy(button, true, "正在保存…");
  try {
    const result = await api("/api/settings/server", {
      method: "PUT",
      body: JSON.stringify({ port: Number(form.elements.port.value) }),
    });
    document.querySelector("#server-port-state").textContent = result.environment_override
      ? `已保存 ${result.configured_port} 端口，但当前被 W1NDVOICE_PORT 环境变量覆盖。`
      : result.restart_required
        ? `已保存 ${result.configured_port} 端口；关闭并重新打开应用后生效。当前仍为 ${result.current_port}。`
        : `当前使用 ${result.current_port} 端口。`;
    notify(result.restart_required ? "端口已保存，重启应用后生效" : "端口设置已保存");
  } catch (error) {
    notify(error.message, true);
  } finally {
    buttonBusy(button, false);
  }
});

document.querySelector("#stream-settings-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  buttonBusy(button, true, "正在保存…");
  try {
    const result = await api("/api/settings/stream", {
      method: "PUT",
      body: JSON.stringify({ per_source_limit: Number(form.elements.per_source_limit.value) }),
    });
    form.elements.per_source_limit.value = result.per_source_limit;
    notify(`每个信息源显示最近 ${result.per_source_limit} 篇`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    buttonBusy(button, false);
  }
});

document.querySelector("#fetch-all")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  buttonBusy(button, true, "正在抓取…");
  try {
    const data = await api("/api/fetch-all", { method: "POST" });
    const changed = data.results.reduce((sum, item) => sum + (item.changed || 0), 0);
    notify(`抓取完成，新增或更新 ${changed} 条`);
    window.setTimeout(() => location.reload(), 700);
  } catch (error) {
    notify(error.message, true);
    buttonBusy(button, false);
  }
});

document.querySelectorAll(".fetch-one").forEach((button) => {
  button.addEventListener("click", async () => {
    buttonBusy(button, true, "…");
    try {
      const data = await api(`/api/sources/${button.dataset.id}/fetch`, { method: "POST" });
      notify(`抓取完成，新增或更新 ${data.changed} 条`);
      window.setTimeout(() => location.reload(), 600);
    } catch (error) {
      notify(error.message, true);
      buttonBusy(button, false);
    }
  });
});

document.querySelectorAll(".delete-source").forEach((button) => {
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const name = button.dataset.name || "该信息源";
    if (!window.confirm(`删除“${name}”及其已抓取文章？此操作无法撤销。`)) return;
    buttonBusy(button, true, "…");
    try {
      await api(`/api/sources/${button.dataset.id}`, { method: "DELETE" });
      location.reload();
    } catch (error) {
      notify(error.message, true);
      buttonBusy(button, false);
    }
  });
});

document.querySelectorAll(".delete-category").forEach((button) => {
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const category = button.dataset.category;
    const count = button.dataset.count;
    if (!window.confirm(`删除分类“${category}”及其中 ${count} 个信息源和所有文章？此操作无法撤销。`)) return;
    buttonBusy(button, true, "…");
    try {
      await api(`/api/categories?name=${encodeURIComponent(category)}`, { method: "DELETE" });
      location.reload();
    } catch (error) {
      notify(error.message, true);
      buttonBusy(button, false);
    }
  });
});

document.querySelectorAll(".delete-article").forEach((button) => {
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const title = button.dataset.title || "该条目";
    if (!window.confirm(`确定删除“${title}”吗？下次重新抓取该来源时可能再次收录。`)) return;
    buttonBusy(button, true, "…");
    try {
      await api(`/api/articles/${button.dataset.id}`, { method: "DELETE" });
      notify("条目已删除");
      window.setTimeout(() => location.reload(), 350);
    } catch (error) {
      notify(error.message, true);
      buttonBusy(button, false);
    }
  });
});

function setAnalysisBadge(container, selector, tag, className, label) {
  let badge = container.querySelector(selector);
  if (!label) {
    badge?.remove();
    return;
  }
  if (!badge) {
    badge = document.createElement(tag);
    container.insertBefore(badge, container.querySelector(".view-analysis, .analyze"));
  }
  badge.className = className;
  badge.textContent = label;
}

function updateArticleAnalysis(article, result) {
  if (result.ai_status === "done") {
    const summary = article.querySelector(".article-card .summary, .article-card .excerpt");
    summary.className = "summary";
    summary.textContent = result.summary;
    article.dataset.search += " " + result.summary;

    const risk = ["critical", "high", "medium", "low"].includes(result.risk_level)
      ? result.risk_level : "";
    setAnalysisBadge(
      article.querySelector(".article-quick-meta"),
      ".article-importance", "b", "article-importance",
      result.importance == null ? "" : "重要度 " + result.importance
    );
    setAnalysisBadge(
      article.querySelector(".article-quick-meta"),
      ".risk", "b", "risk " + risk, risk
    );
    setAnalysisBadge(
      article.querySelector(".card-meta"),
      ".risk", "span", "risk " + risk, risk
    );
    const card = article.querySelector(".article-card");
    let tags = card.querySelector(".tags");
    if (result.tags.length) {
      if (!tags) {
        tags = document.createElement("div");
        tags.className = "tags";
        card.insertBefore(tags, card.querySelector("footer"));
      }
      tags.replaceChildren(...result.tags.map((tag) => {
        const item = document.createElement("span");
        item.textContent = "#" + tag;
        return item;
      }));
    } else {
      tags?.remove();
    }
    setAnalysisBadge(
      card.querySelector("footer"),
      ".score", "span", "score",
      result.importance == null ? "" : "重要度 " + result.importance
    );
  }

  if (result.ai_status === "done" || result.ai_status === "failed") {
    const footer = article.querySelector(".article-card footer");
    let viewButton = footer.querySelector(".view-analysis");
    if (!viewButton) {
      viewButton = document.createElement("button");
      viewButton.type = "button";
      footer.insertBefore(viewButton, footer.querySelector(".analyze"));
    }
    viewButton.className = result.ai_status === "failed"
      ? "text-button error-link view-analysis" : "text-button view-analysis";
    viewButton.dataset.id = footer.querySelector(".analyze").dataset.id;
    viewButton.textContent = result.ai_status === "failed" ? "查看失败原因" : "AI 分析结果";
  }
  article.querySelector(".analyze").textContent =
    result.ai_status === "done" ? "重新分析" : "AI 分析";
}

document.querySelectorAll(".analyze").forEach((button) => {
  button.addEventListener("click", async () => {
    const article = button.closest(".intel-article");
    buttonBusy(button, true, "分析中…");
    try {
      const result = await api(`/api/articles/${button.dataset.id}/analyze`, { method: "POST" });
      buttonBusy(button, false);
      updateArticleAnalysis(article, { ...result, ai_status: "done" });
      notify("AI 分析完成");
    } catch (error) {
      buttonBusy(button, false);
      try {
        const current = await api(`/api/articles/${button.dataset.id}/analysis`);
        updateArticleAnalysis(article, current);
      } catch (_) { /* Keep the current card if its state cannot be read. */ }
      notify(error.message, true);
    }
  });
});

const analysisDialog = document.querySelector("#analysis-dialog");

document.querySelector("#article-grid")?.addEventListener("click", async (event) => {
  const button = event.target.closest(".view-analysis");
  if (button) {
    buttonBusy(button, true, "读取中…");
    try {
      const result = await api(`/api/articles/${button.dataset.id}/analysis`);
      document.querySelector("#analysis-article-title").textContent = result.title;
      document.querySelector("#analysis-summary").textContent = result.ai_status === "failed"
        ? `分析失败：${result.ai_error || "没有错误详情"}`
        : result.summary;
      document.querySelector("#analysis-importance").textContent = result.importance == null
        ? "尚无重要度"
        : `重要度 ${result.importance}`;
      document.querySelector("#analysis-risk").textContent = result.risk_level
        ? `风险 ${result.risk_level.toUpperCase()}`
        : "非漏洞内容";
      const analyzedAt = result.analyzed_at ? new Date(result.analyzed_at) : null;
      document.querySelector("#analysis-time").textContent = analyzedAt && !Number.isNaN(analyzedAt.valueOf())
        ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(analyzedAt)
        : "未完成分析";
      const tagBox = document.querySelector("#analysis-tags");
      tagBox.replaceChildren(...result.tags.map((tag) => {
        const item = document.createElement("span");
        item.textContent = `#${tag}`;
        return item;
      }));
      const sourceLink = document.querySelector("#analysis-source");
      sourceLink.href = result.url;
      analysisDialog.showModal();
    } catch (error) {
      notify(error.message, true);
    } finally {
      buttonBusy(button, false);
    }
  }
});

document.querySelector(".dialog-close")?.addEventListener("click", () => analysisDialog.close());
analysisDialog?.addEventListener("click", (event) => {
  if (event.target === analysisDialog) analysisDialog.close();
});

document.querySelector("#article-search")?.addEventListener("input", (event) => {
  const query = event.target.value.trim().toLocaleLowerCase();
  document.querySelectorAll(".intel-group").forEach((group) => {
    const categoryMatches = group.dataset.search.toLocaleLowerCase().includes(query);
    let visibleSources = 0;
    group.querySelectorAll(".intel-source").forEach((source) => {
      const sourceMatches = categoryMatches || source.dataset.search.toLocaleLowerCase().includes(query);
      let visibleArticles = 0;
      source.querySelectorAll(".intel-article").forEach((article) => {
        const matches = sourceMatches || article.dataset.search.toLocaleLowerCase().includes(query);
        article.classList.toggle("hidden", !matches);
        if (matches) visibleArticles += 1;
        if (query && matches) article.open = true;
      });
      const visible = !query || sourceMatches || visibleArticles > 0;
      source.classList.toggle("hidden", !visible);
      if (visible) visibleSources += 1;
      if (query && visible) source.open = true;
    });
    group.classList.toggle("hidden", Boolean(query) && visibleSources === 0);
    if (query && visibleSources > 0) group.open = true;
  });
});

document.querySelectorAll("time[data-time]").forEach((node) => {
  const date = new Date(node.dataset.time);
  if (!Number.isNaN(date.valueOf())) node.textContent = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
});

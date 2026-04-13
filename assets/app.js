const state = {
  route: "public",
  config: null,
  user: null,
  dashboard: null,
  admin: null,
  overview: null,
  adminUsers: [],
  accounts: [],
  providers: [],
  providerDiagnostics: {},
  snapshots: [],
  editingUserId: null,
  oauth: null,
  oauthTimer: null
};

const planProfiles = {
  starter: { dailyQuota: 200000, monthlyQuota: 3000000, requestQuota: 1000, rateLimitRpm: 30 },
  growth: { dailyQuota: 600000, monthlyQuota: 10000000, requestQuota: 5000, rateLimitRpm: 80 },
  partner: { dailyQuota: 1500000, monthlyQuota: 30000000, requestQuota: 15000, rateLimitRpm: 180 }
};

const $ = (id) => document.getElementById(id);

function detectRoute() {
  const host = window.location.hostname.toLowerCase();
  const path = window.location.pathname.replace(/\/+$/, "");
  return path === "/admin" || path.startsWith("/admin/") || host.startsWith("admin.") ? "admin" : "public";
}

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : "0";
}

function formatMoney(value) {
  const number = Number(value || 0);
  return `$${number.toFixed(4)}`;
}

function formatBytes(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = number;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = size >= 10 || index === 0 ? 0 : 1;
  return `${size.toFixed(digits)} ${units[index]}`;
}

function shortSecret(value) {
  const text = String(value || "");
  if (text.length <= 20) return text;
  return `${text.slice(0, 10)}...${text.slice(-6)}`;
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function api(path, options = {}) {
  const requestOptions = {
    method: options.method || "GET",
    headers: { ...(options.headers || {}) },
    credentials: "same-origin"
  };

  if (options.body !== undefined) {
    requestOptions.headers["Content-Type"] = "application/json";
    requestOptions.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, requestOptions);
  const text = await response.text();
  let payload = {};

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      payload = { message: text };
    }
  }

  if (!response.ok) {
    throw new Error(payload.error || payload.message || `Request failed: ${response.status}`);
  }

  return payload;
}

function showFlash(message, type = "success") {
  const node = $("flashMessage");
  node.textContent = message;
  node.className = `flash-message ${type}`;
  window.clearTimeout(showFlash.timer);
  showFlash.timer = window.setTimeout(() => {
    node.className = "flash-message is-hidden";
  }, 2800);
}

function setMessage(id, message, isError = false) {
  const node = $(id);
  if (!node) return;
  node.textContent = message;
  node.dataset.state = isError ? "error" : "default";
}

function clearMessage(id) {
  setMessage(id, "", false);
}

function applyPlanDefaults(form, planKey) {
  const profile = planProfiles[planKey] || planProfiles.starter;
  for (const [field, value] of Object.entries(profile)) {
    if (form.elements[field]) {
      form.elements[field].value = value;
    }
  }
}

function updateSnippet() {
  const apiKey = state.dashboard && state.dashboard.user
    ? (state.dashboard.user.apiKey || "请在对应入口获取 API Key")
    : "sk-your-key";
  const baseUrl = state.dashboard && state.dashboard.user
    ? state.dashboard.user.baseUrl
    : ((state.config && state.config.apiBaseUrl) || "https://example.com/v1");
  $("sdkSnippet").textContent = `from openai import OpenAI

client = OpenAI(
    api_key="${apiKey}",
    base_url="${baseUrl}"
)`;
}

function renderRoute() {
  document.body.dataset.route = state.route;
  $("publicScreen").classList.toggle("is-hidden", state.route !== "public");
  $("adminScreen").classList.toggle("is-hidden", state.route !== "admin");
  document.title = state.route === "admin" ? "Kiro Relay Admin" : "Kiro Relay";
}

function renderConfig() {
  if (!state.config) return;
  $("workspaceBaseUrl").textContent = state.dashboard && state.dashboard.user ? state.dashboard.user.baseUrl : state.config.apiBaseUrl;
  updateSnippet();
  state.providers = state.config.providers || [];
  renderProviderSelects();
  renderEntryGrid("publicEntryGrid", "public");
  renderEntryGrid("adminEntryGrid", "admin");
}

function renderUsageChart(items) {
  const container = $("usageChart");
  const series = items && items.length
    ? items
    : Array.from({ length: 7 }, (_, index) => ({ label: `D${index + 1}`, count: 0 }));
  const max = Math.max(...series.map((item) => Number(item.count || 0)), 1);

  container.innerHTML = series
    .map((item) => {
      const height = Math.max(12, Math.round((Number(item.count || 0) / max) * 100));
      return `
        <div class="usage-bar">
          <div class="usage-bar-track">
            <div class="usage-bar-fill" style="height:${height}%"></div>
          </div>
          <strong>${escapeHtml(formatNumber(item.count || 0))}</strong>
          <span>${escapeHtml(item.label || "-")}</span>
        </div>
      `;
    })
    .join("");
}

function renderQuotaList(items) {
  $("quotaList").innerHTML = (items || [])
    .map(
      (item) => `
        <article>
          <span>${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
        </article>
      `
    )
    .join("");
}

function renderWorkspace() {
  const ready = Boolean(state.dashboard);
  $("publicAuthCard").classList.toggle("is-hidden", ready);
  $("workspaceShell").classList.toggle("is-hidden", !ready);

  $("workspaceTitle").textContent = ready ? state.dashboard.user.workspace : "-";
  $("workspaceEmail").textContent = ready ? state.dashboard.user.email : "-";
  $("workspaceProvider").textContent = ready
    ? `${state.dashboard.user.providerLabel || state.dashboard.user.providerKey || "-"}`
    : "-";
  $("workspaceApiKey").textContent = ready ? (state.dashboard.user.apiKey || "该套餐通过外部入口提供 Key") : "-";
  $("workspaceBaseUrl").textContent = ready ? state.dashboard.user.baseUrl : ((state.config && state.config.apiBaseUrl) || "-");
  $("metricRequests30d").textContent = formatNumber(state.dashboard && state.dashboard.metrics ? state.dashboard.metrics.requests30d : 0);
  $("metricTokens30d").textContent = formatNumber(state.dashboard && state.dashboard.metrics ? state.dashboard.metrics.tokens30d : 0);
  $("metricTodayRequests").textContent = formatNumber(state.dashboard && state.dashboard.metrics ? state.dashboard.metrics.todayRequests : 0);
  $("metricQuotaRemaining").textContent = formatNumber(state.dashboard && state.dashboard.metrics ? state.dashboard.metrics.quotaRemaining : 0);
  $("metricMonthlyCost").textContent = formatMoney(state.dashboard && state.dashboard.metrics ? state.dashboard.metrics.monthlyCostUsd : 0);

  renderUsageChart(state.dashboard ? state.dashboard.daily : null);
  renderQuotaList(state.dashboard ? state.dashboard.quotas : null);
  updateSnippet();

  const isKiro = ready && state.dashboard.user && state.dashboard.user.providerKey === "kiro";
  $("rotateOwnKeyButton").classList.toggle("is-hidden", !ready || !isKiro);
  $("openProviderEntryButton").classList.toggle("is-hidden", !ready || isKiro);
  $("copyOwnKeyButton").classList.toggle("is-hidden", !ready || !isKiro);
}

function renderOverview() {
  $("adminUserCount").textContent = formatNumber(state.overview && state.overview.portal ? state.overview.portal.userCount : 0);
  $("adminEnabledUserCount").textContent = formatNumber(state.overview && state.overview.portal ? state.overview.portal.enabledUserCount : 0);
  $("adminAccountCount").textContent = formatNumber(state.overview && state.overview.upstream ? state.overview.upstream.currentAccountCount : 0);
  if (state.overview && state.overview.upstream && state.overview.upstream.reachable) {
    $("adminSelectionMode").textContent = state.overview.upstream.accountSelectionMode || "-";
  } else {
    $("adminSelectionMode").textContent = "Kiro offline";
  }
}

function renderProviderSelects() {
  const signupSelect = $("signupProviderSelect");
  const adminSelect = $("adminProviderSelect");
  const currentSignup = signupSelect ? signupSelect.value : "kiro";
  const currentAdmin = adminSelect ? adminSelect.value : "kiro";
  const publicProviders = state.providers.filter((provider) => provider.key === "kiro" || provider.enabled);
  const adminProviders = state.providers.length ? state.providers : [{ key: "kiro", label: "Kiro Relay" }];

  if (signupSelect) {
    signupSelect.innerHTML = publicProviders
      .map((provider) => `<option value="${escapeHtml(provider.key)}">${escapeHtml(provider.label)}</option>`)
      .join("");
    signupSelect.value = publicProviders.some((provider) => provider.key === currentSignup)
      ? currentSignup
      : (publicProviders[0] ? publicProviders[0].key : "kiro");
  }

  if (adminSelect) {
    adminSelect.innerHTML = adminProviders
      .map((provider) => `<option value="${escapeHtml(provider.key)}">${escapeHtml(provider.label)}</option>`)
      .join("");
    adminSelect.value = adminProviders.some((provider) => provider.key === currentAdmin)
      ? currentAdmin
      : (adminProviders[0] ? adminProviders[0].key : "kiro");
  }
}

function providerTargetUrl(provider, audience = "public") {
  if (!provider) return "";
  return audience === "admin"
    ? (provider.adminUrl || provider.publicUrl || provider.apiBaseUrl || "")
    : (provider.publicUrl || provider.apiBaseUrl || provider.adminUrl || "");
}

function providerStatusMeta(provider) {
  const health = provider && provider.health;
  if (!provider || !provider.configured) {
    return { label: "未配置", className: "status-pill is-pending" };
  }
  if (!health) {
    return { label: provider.kind === "native" ? "内置" : "已接入", className: "status-pill" };
  }
  if (health.reachable) {
    return { label: `在线${health.statusCode ? ` ${health.statusCode}` : ""}`, className: "status-pill" };
  }
  if (health.status === "unconfigured") {
    return { label: "未配置", className: "status-pill is-pending" };
  }
  return { label: "离线", className: "status-pill is-offline" };
}

function entryCardTemplate(provider, audience = "public") {
  const targetUrl = providerTargetUrl(provider, audience);
  const status = providerStatusMeta(provider);
  const isNative = provider.key === "kiro";
  const actionLabel = isNative
    ? (audience === "admin" ? "使用当前后台" : "使用当前入口")
    : (provider.embedMode === "new_tab" ? "新窗口打开" : "进入入口");

  return `
    <article class="entry-card">
      <div class="entry-card-head">
        <div>
          <strong>${escapeHtml(provider.label || provider.key)}</strong>
          <p>${escapeHtml(provider.description || "")}</p>
        </div>
        <span class="${status.className}">${escapeHtml(status.label)}</span>
      </div>
      <div class="entry-meta">
        <article>
          <span class="label">${audience === "admin" ? "管理地址" : "用户地址"}</span>
          <code>${escapeHtml(targetUrl || "未配置")}</code>
        </article>
        ${provider.apiBaseUrl ? `
          <article>
            <span class="label">API Base URL</span>
            <code>${escapeHtml(provider.apiBaseUrl)}</code>
          </article>
        ` : ""}
      </div>
      <div class="provider-actions">
        <button
          class="button button-primary"
          type="button"
          data-action="${isNative ? `focus-native-${audience}` : "open-provider-entry"}"
          data-url="${escapeHtml(targetUrl)}"
          data-mode="${escapeHtml(provider.embedMode || "link")}"
        >
          ${escapeHtml(actionLabel)}
        </button>
      </div>
    </article>
  `;
}

function renderEntryGrid(nodeId, audience = "public") {
  const node = $(nodeId);
  if (!node) return;
  const providers = state.providers.filter((provider) => {
    if (provider.key === "kiro") return true;
    if (audience === "admin") return provider.configured || provider.enabled;
    return provider.enabled;
  });
  node.innerHTML = providers.length
    ? providers.map((provider) => entryCardTemplate(provider, audience)).join("")
    : '<article class="entry-card"><strong>暂无可用入口</strong><p>请先在管理后台配置入口。</p></article>';
}

function providerCardTemplate(provider) {
  const status = providerStatusMeta(provider);
  if (provider.readOnly) {
    return `
      <article class="provider-card">
        <div class="provider-card-head">
          <div>
            <strong>${escapeHtml(provider.label)}</strong>
            <p>${escapeHtml(provider.description || "")}</p>
          </div>
          <span class="${status.className}">${escapeHtml(status.label)}</span>
        </div>
        <div class="provider-url-list">
          <article>
            <span class="label">用户入口</span>
            <code>${escapeHtml(provider.publicUrl || "-")}</code>
          </article>
          <article>
            <span class="label">管理入口</span>
            <code>${escapeHtml(provider.adminUrl || "-")}</code>
          </article>
          <article>
            <span class="label">API Base URL</span>
            <code>${escapeHtml(provider.apiBaseUrl || "-")}</code>
          </article>
        </div>
      </article>
    `;
  }

  return `
    <article class="provider-card">
      <div class="provider-card-head">
        <div>
          <strong>${escapeHtml(provider.label)}</strong>
          <p>${escapeHtml(provider.description || "")}</p>
        </div>
        <span class="${status.className}">${escapeHtml(status.label)}</span>
      </div>
      <form data-provider-form="${escapeHtml(provider.key)}">
        <div class="form-grid">
          <label>
            <span>显示名称</span>
            <input type="text" name="label" value="${escapeHtml(provider.label || "")}" required>
          </label>
          <label>
            <span>打开方式</span>
            <select name="embedMode">
              <option value="link" ${provider.embedMode === "link" ? "selected" : ""}>当前窗口</option>
              <option value="new_tab" ${provider.embedMode === "new_tab" ? "selected" : ""}>新窗口</option>
              <option value="iframe" ${provider.embedMode === "iframe" ? "selected" : ""}>iframe 预留</option>
            </select>
          </label>
          <label class="full-width">
            <span>说明</span>
            <input type="text" name="description" value="${escapeHtml(provider.description || "")}">
          </label>
          <label>
            <span>用户入口 URL</span>
            <input type="url" name="publicUrl" value="${escapeHtml(provider.publicUrl || "")}" placeholder="https://sub2api.example.com">
          </label>
          <label>
            <span>管理入口 URL</span>
            <input type="url" name="adminUrl" value="${escapeHtml(provider.adminUrl || "")}" placeholder="https://sub2api.example.com/admin">
          </label>
          <label>
            <span>管理 API Key</span>
            <input type="password" name="adminApiKey" value="" placeholder="${provider.hasAdminApiKey ? '已保存，留空表示不修改' : '粘贴 sub2api admin api key'}">
            <span class="field-help">${provider.hasAdminApiKey ? "已保存管理 API Key，留空不改。" : "未配置管理 API Key，无法自动同步创建 sub2api 用户。"}</span>
          </label>
          <label>
            <span>API Base URL</span>
            <input type="url" name="apiBaseUrl" value="${escapeHtml(provider.apiBaseUrl || "")}" placeholder="https://sub2api.example.com/v1">
          </label>
          <label>
            <span>健康检查 URL</span>
            <input type="url" name="healthUrl" value="${escapeHtml(provider.healthUrl || "")}" placeholder="https://sub2api.example.com/health">
          </label>
          <label>
            <span>默认分组 ID</span>
            <input type="text" name="defaultAllowedGroups" value="${escapeHtml((provider.defaultAllowedGroups || []).join(', '))}" placeholder="1,2,3">
            <span class="field-help">创建 sub2api 用户时自动写入的 allowed_groups。</span>
          </label>
          <label>
            <span>默认并发</span>
            <input type="number" min="0" name="defaultConcurrency" value="${escapeHtml(String(provider.defaultConcurrency || 0))}">
          </label>
          <label>
            <span>初始余额</span>
            <input type="number" min="0" step="0.01" name="initialBalance" value="${escapeHtml(String(provider.initialBalance || 0))}">
          </label>
          <label class="checkbox-field full-width">
            <input type="checkbox" name="enabled" ${provider.enabled ? "checked" : ""}>
            <span>向用户展示该入口</span>
          </label>
        </div>
        <div class="provider-actions">
          <button class="button button-primary" type="submit">保存配置</button>
          <button class="button button-secondary" type="button" data-action="open-provider-entry" data-url="${escapeHtml(provider.publicUrl || "")}" data-mode="${escapeHtml(provider.embedMode || "link")}">打开用户入口</button>
          <button class="button button-secondary" type="button" data-action="open-provider-entry" data-url="${escapeHtml(provider.adminUrl || "")}" data-mode="${escapeHtml(provider.embedMode || "link")}">打开管理入口</button>
        </div>
      </form>
    </article>
  `;
}

function renderProviderAdminCards() {
  const node = $("providerAdminGrid");
  if (!node) return;
  node.innerHTML = state.providers.length
    ? state.providers.map(providerCardTemplate).join("")
    : '<article class="provider-card"><strong>暂无入口配置</strong></article>';
}

function userRowTemplate(user) {
  const isKiro = user.providerKey === "kiro";
  return `
    <tr>
      <td>${escapeHtml(user.workspace)}</td>
      <td>${escapeHtml(user.email)}</td>
      <td>${escapeHtml(user.providerLabel || user.providerKey || "-")}</td>
      <td>${escapeHtml(user.planLabel)}</td>
      <td><code title="${escapeHtml(user.apiKey || "")}">${escapeHtml(user.apiKey ? shortSecret(user.apiKey) : "-")}</code></td>
      <td>${escapeHtml(formatNumber(user.upstreamTotals ? (user.upstreamTotals.totalRequests || 0) : 0))}</td>
      <td>${user.enabled ? "enabled" : "disabled"}</td>
      <td>
        <div class="table-actions">
          <button class="text-button" data-action="edit-user" data-id="${escapeHtml(user.id)}">编辑</button>
          <button class="text-button" data-action="toggle-user" data-id="${escapeHtml(user.id)}">${user.enabled ? "停用" : "启用"}</button>
          ${isKiro ? `<button class="text-button" data-action="rotate-user-key" data-id="${escapeHtml(user.id)}">轮换 Key</button>` : ""}
          ${isKiro ? `<button class="text-button" data-action="copy-user-key" data-id="${escapeHtml(user.id)}">复制 Key</button>` : ""}
          <button class="text-button" data-action="delete-user" data-id="${escapeHtml(user.id)}">删除</button>
        </div>
      </td>
    </tr>
  `;
}

function renderUsers() {
  $("adminUsersBody").innerHTML = state.adminUsers.length
    ? state.adminUsers.map(userRowTemplate).join("")
    : '<tr><td colspan="8">暂无用户</td></tr>';
}

function accountId(account) {
  return account.id || account.account_id || account.accountId || account.user_id || "";
}

function accountLabel(account) {
  return account.label || account.email || account.account_id || account.id || "-";
}

function accountUpdatedAt(account) {
  return account.updated_at || account.last_used_at || account.last_refresh_at || account.created_at || "-";
}

function renderAccounts() {
  $("accountPoolBody").innerHTML = state.accounts.length
    ? state.accounts
        .map((account) => {
          const id = accountId(account);
          return `
            <tr>
              <td>${escapeHtml(accountLabel(account))}</td>
              <td>${escapeHtml(account.status || "-")}</td>
              <td>${account.enabled === false ? "false" : "true"}</td>
              <td>${escapeHtml(String(accountUpdatedAt(account)))}</td>
              <td>
                <div class="table-actions">
                  <button class="text-button" data-action="refresh-account" data-id="${escapeHtml(id)}">刷新</button>
                  <button class="text-button" data-action="toggle-account" data-id="${escapeHtml(id)}">${account.enabled === false ? "启用" : "停用"}</button>
                  <button class="text-button" data-action="delete-account" data-id="${escapeHtml(id)}">删除</button>
                </div>
              </td>
            </tr>
          `;
        })
        .join("")
    : '<tr><td colspan="5">账号池为空</td></tr>';
}

function snapshotRowTemplate(snapshot) {
  return `
    <tr>
      <td><code title="${escapeHtml(snapshot.id)}">${escapeHtml(snapshot.id)}</code></td>
      <td>${escapeHtml(snapshot.createdAt || "-")}</td>
      <td>${escapeHtml(formatBytes(snapshot.archiveSizeBytes || 0))}</td>
      <td>${escapeHtml(formatNumber(snapshot.items ? snapshot.items.length : 0))}</td>
      <td>${escapeHtml(snapshot.createdBy || "-")}</td>
      <td>
        <div class="table-actions">
          <a class="text-button" href="/api/admin/snapshots/${encodeURIComponent(snapshot.id)}/download">下载</a>
          <button class="text-button" data-action="copy-restore-command" data-id="${escapeHtml(snapshot.id)}">复制恢复命令</button>
          <button class="text-button" data-action="copy-snapshot-path" data-id="${escapeHtml(snapshot.id)}">复制路径</button>
        </div>
      </td>
    </tr>
  `;
}

function renderSnapshots() {
  $("snapshotBody").innerHTML = state.snapshots.length
    ? state.snapshots.map(snapshotRowTemplate).join("")
    : '<tr><td colspan="6">暂无快照</td></tr>';
}

function renderOAuth() {
  $("oauthStatusText").textContent = state.oauth ? (state.oauth.status || "-") : "-";
  $("oauthUserCode").textContent = state.oauth ? (state.oauth.userCode || "-") : "-";
  $("oauthLink").textContent = state.oauth ? (state.oauth.verificationUriComplete || "-") : "-";
  $("oauthLink").href = state.oauth ? (state.oauth.verificationUriComplete || "#") : "#";
}

function resetAdminForm() {
  state.editingUserId = null;
  const form = $("adminUserForm");
  form.reset();
  form.elements.enabled.checked = true;
  form.elements.provider.disabled = false;
  form.elements.provider.value = "kiro";
  form.elements.plan.value = "starter";
  applyPlanDefaults(form, "starter");
  $("adminUserSubmit").textContent = "保存";
  $("cancelEditButton").classList.add("is-hidden");
  $("editingHint").textContent = "新建用户";
}

function fillAdminForm(user) {
  const form = $("adminUserForm");
  state.editingUserId = user.id;
  form.elements.workspace.value = user.workspace;
  form.elements.email.value = user.email;
  form.elements.provider.value = user.providerKey || "kiro";
  form.elements.provider.disabled = true;
  form.elements.password.value = "";
  form.elements.plan.value = user.plan;
  form.elements.dailyQuota.value = user.dailyQuota;
  form.elements.monthlyQuota.value = user.monthlyQuota;
  form.elements.requestQuota.value = user.requestQuota;
  form.elements.rateLimitRpm.value = user.rateLimitRpm;
  form.elements.usecase.value = user.usecase || "";
  form.elements.notes.value = user.notes || "";
  form.elements.enabled.checked = Boolean(user.enabled);
  $("adminUserSubmit").textContent = "保存修改";
  $("cancelEditButton").classList.remove("is-hidden");
  $("editingHint").textContent = `编辑 ${user.workspace}`;
}

function readAdminFormPayload() {
  const form = $("adminUserForm");
  const formData = new FormData(form);
  return {
    workspace: String(formData.get("workspace") || ""),
    email: String(formData.get("email") || ""),
    providerKey: String(form.elements.provider.value || "kiro"),
    password: String(formData.get("password") || ""),
    plan: String(formData.get("plan") || "starter"),
    dailyQuota: Number(formData.get("dailyQuota") || 0),
    monthlyQuota: Number(formData.get("monthlyQuota") || 0),
    requestQuota: Number(formData.get("requestQuota") || 0),
    rateLimitRpm: Number(formData.get("rateLimitRpm") || 0),
    usecase: String(formData.get("usecase") || ""),
    notes: String(formData.get("notes") || ""),
    enabled: formData.get("enabled") === "on"
  };
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    showFlash("已复制");
  } catch (error) {
    showFlash(error.message || "复制失败", "error");
  }
}

function openEntryUrl(url, mode = "link") {
  if (!url) {
    showFlash("入口尚未配置", "error");
    return;
  }
  if (mode === "new_tab") {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  window.location.href = url;
}

function startOauthPolling() {
  window.clearInterval(state.oauthTimer);
  state.oauthTimer = window.setInterval(async () => {
    if (!state.oauth || !state.oauth.authId) return;
    try {
      const payload = await api(`/api/admin/oauth/status/${encodeURIComponent(state.oauth.authId)}`);
      state.oauth = { ...state.oauth, ...payload };
      renderOAuth();
      if (payload.status && payload.status !== "pending") {
        window.clearInterval(state.oauthTimer);
      }
    } catch (error) {
      window.clearInterval(state.oauthTimer);
    }
  }, 5000);
}

async function loadConfig() {
  state.config = await api("/api/config");
  renderConfig();
}

async function loadUserSession() {
  try {
    state.dashboard = await api("/api/dashboard");
    state.user = state.dashboard.user;
  } catch (error) {
    state.dashboard = null;
    state.user = null;
  }
  renderWorkspace();
}

async function refreshAdminData() {
  if (!state.admin) return;
  const [overviewResult, usersResult, accountsResult, snapshotsResult, providersResult] = await Promise.allSettled([
    api("/api/admin/overview"),
    api("/api/admin/users"),
    api("/api/admin/accounts"),
    api("/api/admin/snapshots"),
    api("/api/admin/providers")
  ]);

  state.overview = overviewResult.status === "fulfilled" ? overviewResult.value : null;
  state.adminUsers = usersResult.status === "fulfilled" ? (usersResult.value.users || []) : [];
  state.accounts = accountsResult.status === "fulfilled" ? (accountsResult.value.accounts || []) : [];
  state.snapshots = snapshotsResult.status === "fulfilled" ? (snapshotsResult.value.snapshots || []) : [];
  state.providers = providersResult.status === "fulfilled"
    ? (providersResult.value.providers || [])
    : ((state.config && state.config.providers) || state.providers || []);
  if (state.config) {
    state.config.providers = state.providers;
  }

  renderOverview();
  renderUsers();
  renderAccounts();
  renderSnapshots();
  renderProviderSelects();
  renderEntryGrid("publicEntryGrid", "public");
  renderEntryGrid("adminEntryGrid", "admin");
  renderProviderAdminCards();

  const failed = [overviewResult, usersResult, accountsResult, snapshotsResult, providersResult]
    .filter((result) => result.status === "rejected")
    .map((result) => result.reason && result.reason.message ? result.reason.message : "请求失败");
  if (failed.length) {
    showFlash(`部分数据刷新失败: ${failed[0]}`, "error");
  }
}

async function loadAdminSession() {
  try {
    const payload = await api("/api/admin/me");
    state.admin = payload.admin;
    $("adminSessionText").textContent = payload.admin.displayName;
    await refreshAdminData();
  } catch (error) {
    state.admin = null;
    state.snapshots = [];
  }
  $("adminLoginShell").classList.toggle("is-hidden", Boolean(state.admin));
  $("adminShell").classList.toggle("is-hidden", !state.admin);
  renderProviderAdminCards();
}

function bindPublicEvents() {
  $("publicEntryGrid").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "focus-native-public") {
      $("publicAuthCard").scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (button.dataset.action === "open-provider-entry") {
      openEntryUrl(button.dataset.url || "", button.dataset.mode || "link");
    }
  });

  document.querySelectorAll("[data-user-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.userTab;
      document.querySelectorAll("[data-user-tab]").forEach((node) => {
        node.classList.toggle("is-active", node === button);
      });
      $("loginForm").classList.toggle("is-active", target === "login");
      $("signupForm").classList.toggle("is-active", target === "signup");
      $("publicAuthCard").querySelector(".screen-title").textContent = target === "login" ? "登录" : "注册";
      clearMessage("userAuthMessage");
    });
  });

  $("signupPlanSelect").addEventListener("change", (event) => {
    applyPlanDefaults($("signupForm"), event.target.value);
  });

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessage("userAuthMessage");
    const formData = new FormData(event.currentTarget);
    try {
      state.dashboard = await api("/api/auth/login", {
        method: "POST",
        body: {
          email: String(formData.get("email") || ""),
          password: String(formData.get("password") || "")
        }
      });
      state.user = state.dashboard.user;
      renderWorkspace();
      showFlash("登录成功");
    } catch (error) {
      setMessage("userAuthMessage", error.message, true);
    }
  });

  $("signupForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessage("userAuthMessage");
    const formData = new FormData(event.currentTarget);
    try {
      state.dashboard = await api("/api/auth/register", {
        method: "POST",
        body: {
          workspace: String(formData.get("workspace") || ""),
          providerKey: String(formData.get("provider") || "kiro"),
          email: String(formData.get("email") || ""),
          password: String(formData.get("password") || ""),
          plan: String(formData.get("plan") || "starter"),
          usecase: String(formData.get("usecase") || "")
        }
      });
      state.user = state.dashboard.user;
      renderWorkspace();
      event.currentTarget.reset();
      showFlash("注册成功");
    } catch (error) {
      setMessage("userAuthMessage", error.message, true);
    }
  });

  $("userLogoutButton").addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    state.user = null;
    state.dashboard = null;
    renderWorkspace();
    showFlash("已退出");
  });

  $("rotateOwnKeyButton").addEventListener("click", async () => {
    try {
      state.dashboard = await api("/api/apikey/rotate", { method: "POST" });
      state.user = state.dashboard.user;
      renderWorkspace();
      showFlash("API Key 已更新");
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("openProviderEntryButton").addEventListener("click", () => {
    const provider = state.dashboard && state.dashboard.user ? state.dashboard.user.entry : null;
    openEntryUrl(providerTargetUrl(provider, "public"), provider && provider.embedMode ? provider.embedMode : "link");
  });

  $("copyOwnKeyButton").addEventListener("click", () => copyText(state.dashboard && state.dashboard.user ? state.dashboard.user.apiKey : ""));
  $("copyBaseUrlButton").addEventListener("click", () => copyText(state.dashboard && state.dashboard.user ? state.dashboard.user.baseUrl : ((state.config && state.config.apiBaseUrl) || "")));
  $("copySnippetButton").addEventListener("click", () => copyText($("sdkSnippet").textContent));

  applyPlanDefaults($("signupForm"), "starter");
}

function bindAdminEvents() {
  $("adminEntryGrid").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "focus-native-admin") {
      const target = state.admin ? $("adminShell") : $("adminLoginShell");
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (button.dataset.action === "open-provider-entry") {
      openEntryUrl(button.dataset.url || "", button.dataset.mode || "link");
    }
  });

  $("adminLoginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessage("adminAuthMessage");
    const formData = new FormData(event.currentTarget);
    try {
      const payload = await api("/api/admin/login", {
        method: "POST",
        body: {
          email: String(formData.get("email") || ""),
          password: String(formData.get("password") || "")
        }
      });
      state.admin = payload.admin;
      $("adminSessionText").textContent = payload.admin.displayName;
      $("adminLoginShell").classList.add("is-hidden");
      $("adminShell").classList.remove("is-hidden");
      await refreshAdminData();
      showFlash("登录成功");
    } catch (error) {
      setMessage("adminAuthMessage", error.message, true);
    }
  });

  $("adminLogoutButton").addEventListener("click", async () => {
    await api("/api/admin/logout", { method: "POST" });
    state.admin = null;
    state.overview = null;
    state.adminUsers = [];
    state.accounts = [];
    state.snapshots = [];
    state.providers = (state.config && state.config.providers) || [];
    $("adminLoginShell").classList.remove("is-hidden");
    $("adminShell").classList.add("is-hidden");
    renderOverview();
    renderUsers();
    renderAccounts();
    renderSnapshots();
    renderEntryGrid("adminEntryGrid", "admin");
    renderProviderAdminCards();
    showFlash("已退出");
  });

  $("adminPlanSelect").addEventListener("change", (event) => {
    applyPlanDefaults($("adminUserForm"), event.target.value);
  });

  $("adminUserForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = readAdminFormPayload();
    try {
      if (state.editingUserId) {
        await api(`/api/admin/users/${encodeURIComponent(state.editingUserId)}`, {
          method: "PATCH",
          body: payload
        });
        showFlash("用户已更新");
      } else {
        await api("/api/admin/users", {
          method: "POST",
          body: payload
        });
        showFlash("用户已创建");
      }
      resetAdminForm();
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("cancelEditButton").addEventListener("click", resetAdminForm);
  $("refreshUsersButton").addEventListener("click", refreshAdminData);
  $("refreshAccountsButton").addEventListener("click", refreshAdminData);
  $("refreshProvidersButton").addEventListener("click", refreshAdminData);
  $("snapshotForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      await api("/api/admin/snapshots", {
        method: "POST",
        body: {
          label: String(formData.get("label") || "")
        }
      });
      event.currentTarget.reset();
      showFlash("快照已创建");
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("refreshAllAccountsButton").addEventListener("click", async () => {
    try {
      await api("/api/admin/accounts/refresh-all", { method: "POST" });
      showFlash("已触发刷新");
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("refreshAllQuotasButton").addEventListener("click", async () => {
    try {
      await api("/api/admin/accounts/refresh-quotas", { method: "POST" });
      showFlash("已触发配额刷新");
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("adminUsersBody").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const user = state.adminUsers.find((item) => item.id === button.dataset.id);
    if (!user) return;

    try {
      if (button.dataset.action === "edit-user") {
        fillAdminForm(user);
        return;
      }
      if (button.dataset.action === "toggle-user") {
        await api(`/api/admin/users/${encodeURIComponent(user.id)}`, {
          method: "PATCH",
          body: {
            ...user,
            enabled: !user.enabled,
            dailyQuota: user.dailyQuota,
            monthlyQuota: user.monthlyQuota,
            requestQuota: user.requestQuota,
            rateLimitRpm: user.rateLimitRpm
          }
        });
        showFlash("状态已更新");
      }
      if (button.dataset.action === "rotate-user-key") {
        await api(`/api/admin/users/${encodeURIComponent(user.id)}/rotate-key`, { method: "POST" });
        showFlash("Key 已轮换");
      }
      if (button.dataset.action === "copy-user-key") {
        await copyText(user.apiKey || "");
        showFlash("Key 已复制");
        return;
      }
      if (button.dataset.action === "delete-user") {
        if (!window.confirm(`确认删除 ${user.workspace} ?`)) return;
        await api(`/api/admin/users/${encodeURIComponent(user.id)}`, { method: "DELETE" });
        showFlash("用户已删除");
      }
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("accountPoolBody").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const account = state.accounts.find((item) => accountId(item) === button.dataset.id);
    if (!account) return;

    try {
      if (button.dataset.action === "refresh-account") {
        await api(`/api/admin/accounts/${encodeURIComponent(accountId(account))}/refresh`, { method: "POST" });
        showFlash("账号刷新中");
      }
      if (button.dataset.action === "toggle-account") {
        await api(`/api/admin/accounts/${encodeURIComponent(accountId(account))}`, {
          method: "PATCH",
          body: { enabled: account.enabled === false }
        });
        showFlash("账号状态已更新");
      }
      if (button.dataset.action === "delete-account") {
        if (!window.confirm(`确认删除 ${accountLabel(account)} ?`)) return;
        await api(`/api/admin/accounts/${encodeURIComponent(accountId(account))}`, { method: "DELETE" });
        showFlash("账号已删除");
      }
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("snapshotBody").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const snapshot = state.snapshots.find((item) => item.id === button.dataset.id);
    if (!snapshot) return;

    try {
      if (button.dataset.action === "copy-restore-command") {
        await copyText(snapshot.restoreCommand || "");
        showFlash("恢复命令已复制");
        return;
      }
      if (button.dataset.action === "copy-snapshot-path") {
        await copyText(snapshot.archivePath || "");
        showFlash("路径已复制");
      }
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("providerAdminGrid").addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-provider-form]");
    if (!form) return;
    event.preventDefault();
    const providerKey = form.dataset.providerForm;
    const formData = new FormData(form);
    try {
      await api(`/api/admin/providers/${encodeURIComponent(providerKey)}`, {
        method: "PUT",
        body: {
          label: String(formData.get("label") || ""),
          description: String(formData.get("description") || ""),
          publicUrl: String(formData.get("publicUrl") || ""),
          adminUrl: String(formData.get("adminUrl") || ""),
          adminApiKey: String(formData.get("adminApiKey") || ""),
          apiBaseUrl: String(formData.get("apiBaseUrl") || ""),
          healthUrl: String(formData.get("healthUrl") || ""),
          defaultAllowedGroups: String(formData.get("defaultAllowedGroups") || ""),
          defaultConcurrency: Number(formData.get("defaultConcurrency") || 0),
          initialBalance: Number(formData.get("initialBalance") || 0),
          embedMode: String(formData.get("embedMode") || "link"),
          enabled: formData.get("enabled") === "on"
        }
      });
      showFlash("入口配置已保存");
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("providerAdminGrid").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "open-provider-entry") {
      openEntryUrl(button.dataset.url || "", button.dataset.mode || "link");
    }
  });

  $("oauthForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      state.oauth = await api("/api/admin/oauth/start", {
        method: "POST",
        body: {
          label: String(formData.get("label") || ""),
          enabled: formData.get("enabled") === "on"
        }
      });
      renderOAuth();
      startOauthPolling();
      showFlash("授权链接已生成");
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("pollOauthButton").addEventListener("click", async () => {
    if (!state.oauth || !state.oauth.authId) {
      showFlash("请先开始授权", "error");
      return;
    }
    try {
      state.oauth = { ...state.oauth, ...(await api(`/api/admin/oauth/status/${encodeURIComponent(state.oauth.authId)}`)) };
      renderOAuth();
      showFlash("状态已刷新");
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  $("claimOauthButton").addEventListener("click", async () => {
    if (!state.oauth || !state.oauth.authId) {
      showFlash("请先开始授权", "error");
      return;
    }
    try {
      state.oauth = { ...state.oauth, ...(await api(`/api/admin/oauth/claim/${encodeURIComponent(state.oauth.authId)}`, { method: "POST" })) };
      renderOAuth();
      showFlash("已尝试认领");
      await refreshAdminData();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });

  resetAdminForm();
  renderOAuth();
  renderSnapshots();
}

async function bootstrap() {
  state.route = detectRoute();
  renderRoute();
  await loadConfig();

  if (state.route === "admin") {
    bindAdminEvents();
    await loadAdminSession();
    return;
  }

  bindPublicEvents();
  await loadUserSession();
}

bootstrap().catch((error) => {
  showFlash(error.message || "初始化失败", "error");
});

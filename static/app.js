const galleryEl = document.getElementById("gallery");
const currentInfoEl = document.getElementById("current-info");
const liveToggle = document.getElementById("live-toggle");
const liveLabel = document.getElementById("live-label");
const fileInput = document.getElementById("file-input");
const quitBtn = document.getElementById("quit-btn");
const lockDesignsEl = document.getElementById("lock-designs");
const blurSlider = document.getElementById("blur-slider");
const blurValueEl = document.getElementById("blur-value");
const themesEl = document.getElementById("themes");
const themeNameInput = document.getElementById("theme-name");
const saveThemeBtn = document.getElementById("save-theme-btn");

let state = { current: null, live: false, gallery: [] };
let currentLockDesign = null;
let LOCK_DESIGN_IDS = [];

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
}

function render() {
  galleryEl.innerHTML = "";

  if (state.gallery.length === 0) {
    galleryEl.innerHTML = '<div class="empty">No wallpapers yet — import one to get started.</div>';
  }

  for (const item of state.gallery) {
    const card = document.createElement("div");
    card.className = "card" + (item.id === state.current ? " active" : "");
    card.innerHTML = `
      ${item.thumb ? `<img class="thumb" src="/thumbs/${item.thumb}">` : '<div class="thumb"></div>'}
      <div class="meta">
        <span class="name" title="${item.name}">${item.name}</span>
        <span class="badge">${item.animated ? "animated" : "static"}</span>
        <button class="pfp" title="Set as profile picture (login screen avatar)">PFP</button>
        <button class="del" title="Delete">✕</button>
      </div>
    `;
    card.querySelector(".thumb, img")?.addEventListener?.("click", () => select(item.id));
    card.addEventListener("click", (e) => {
      if (e.target.closest(".del") || e.target.closest(".pfp")) return;
      select(item.id);
    });
    card.querySelector(".pfp").addEventListener("click", (e) => {
      e.stopPropagation();
      setProfilePic(item.id);
    });
    card.querySelector(".del").addEventListener("click", (e) => {
      e.stopPropagation();
      del(item.id);
    });
    galleryEl.appendChild(card);
  }

  const current = state.gallery.find((g) => g.id === state.current);
  if (current) {
    currentInfoEl.innerHTML = `Current: <strong>${current.name}</strong>`;
    liveToggle.disabled = !current.animated;
    liveToggle.checked = !!state.live;
    liveLabel.textContent = current.animated
      ? (state.live ? "Live" : "Static")
      : "Live (n/a)";
  } else {
    currentInfoEl.textContent = "No wallpaper selected";
    liveToggle.disabled = true;
    liveToggle.checked = false;
    liveLabel.textContent = "Live";
  }
}

async function refresh() {
  state = await api("/api/state");
  render();
}

async function select(id) {
  state = await api("/api/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  render();
}

async function setProfilePic(id) {
  try {
    await api("/api/set-profile-pic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
  } catch (e) {
    alert("Couldn't set profile picture: " + e.message);
  }
}

async function del(id) {
  if (!confirm("Delete this wallpaper?")) return;
  state = await api("/api/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  render();
}

function renderLockDesigns(designs) {
  lockDesignsEl.innerHTML = "";
  for (const id of designs) {
    const card = document.createElement("div");
    card.className = "design-card" + (id === currentLockDesign ? " active" : "");
    card.textContent = id;
    card.addEventListener("mouseenter", () => {
      api("/api/lock-design/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      }).catch(() => {});
    });
    card.addEventListener("click", () => selectLockDesign(id));
    lockDesignsEl.appendChild(card);
  }
}

async function selectLockDesign(id) {
  try {
    await api("/api/lock-design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    currentLockDesign = id;
    renderLockDesigns(LOCK_DESIGN_IDS);
  } catch (e) {
    alert("Couldn't set lock design: " + e.message);
  }
}

async function loadLockDesign() {
  const data = await api("/api/lock-design");
  currentLockDesign = data.design;
  LOCK_DESIGN_IDS = data.designs;
  renderLockDesigns(LOCK_DESIGN_IDS);
}

async function loadLockBlur() {
  const data = await api("/api/lock-blur");
  const pct = data.blur === null ? 85 : Math.round(data.blur * 100);
  blurSlider.value = pct;
  blurValueEl.textContent = pct + "%";
}

const sendBlur = debounce(async (pct) => {
  try {
    await api("/api/lock-blur", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: pct / 100 }),
    });
  } catch (e) {
    alert("Couldn't set blur: " + e.message);
  }
}, 300);

blurSlider.addEventListener("input", () => {
  blurValueEl.textContent = blurSlider.value + "%";
  sendBlur(Number(blurSlider.value));
});

function renderThemes(themes) {
  themesEl.innerHTML = "";
  if (themes.length === 0) {
    themesEl.innerHTML = '<div class="empty">No themes saved yet.</div>';
    return;
  }
  for (const theme of themes) {
    const card = document.createElement("div");
    card.className = "theme-card";
    card.innerHTML = `
      <span class="name" title="${theme.name}">${theme.name}</span>
      <div class="theme-actions">
        <button class="apply">Apply</button>
        <button class="del" title="Delete">✕</button>
      </div>
    `;
    card.querySelector(".apply").addEventListener("click", () => applyTheme(theme.name));
    card.querySelector(".del").addEventListener("click", () => deleteTheme(theme.name));
    themesEl.appendChild(card);
  }
}

async function loadThemes() {
  const data = await api("/api/themes");
  renderThemes(data.themes);
}

async function applyTheme(name) {
  try {
    await api("/api/themes/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    await refresh();
    await loadLockDesign();
    await loadLockBlur();
  } catch (e) {
    alert("Couldn't apply theme: " + e.message);
  }
}

async function deleteTheme(name) {
  if (!confirm(`Delete theme "${name}"?`)) return;
  const data = await api("/api/themes/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  renderThemes(data.themes);
}

saveThemeBtn.addEventListener("click", async () => {
  const name = themeNameInput.value.trim();
  if (!name) return;
  try {
    const data = await api("/api/themes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    themeNameInput.value = "";
    renderThemes(data.themes);
  } catch (e) {
    alert("Couldn't save theme: " + e.message);
  }
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  currentInfoEl.textContent = "Importing…";
  try {
    await api("/api/import", { method: "POST", body: form });
  } catch (e) {
    alert("Import failed: " + e.message);
  }
  fileInput.value = "";
  await refresh();
});

liveToggle.addEventListener("change", async () => {
  try {
    state = await api("/api/toggle-live", { method: "POST" });
  } catch (e) {
    alert(e.message);
  }
  render();
});

quitBtn.addEventListener("click", async () => {
  await api("/api/quit", { method: "POST" }).catch(() => {});
  document.body.innerHTML = "<div style='padding:40px;text-align:center;color:#9298a8'>Server stopped. You can close this tab.</div>";
});

refresh();
loadLockDesign();
loadLockBlur();
loadThemes();

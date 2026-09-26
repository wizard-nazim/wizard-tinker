const galleryEl = document.getElementById("gallery");
const currentInfoEl = document.getElementById("current-info");
const liveToggle = document.getElementById("live-toggle");
const liveLabel = document.getElementById("live-label");
const fileInput = document.getElementById("file-input");
const quitBtn = document.getElementById("quit-btn");

let state = { current: null, live: false, gallery: [] };

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

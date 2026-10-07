"use strict";

(function () {
  const params = new URLSearchParams(location.search);
  const HOST = (params.get("host") || "").trim();
  const statusEl = document.getElementById("status");
  const hostLabel = document.getElementById("hostLabel");
  const cmdPrompt = document.getElementById("cmdPrompt");
  const cmdInput = document.getElementById("cmdInput");
  const fileInput = document.getElementById("fileInput");

  if (!HOST) {
    statusEl.textContent = "No host selected";
    return;
  }
  hostLabel.textContent = HOST;

  const S = {
    active: "L",
    lastClick: { side: null, index: -1, time: 0 },
    drives: ["C:\\"],
    L: { path: "C:\\", items: [], index: 0, marked: {} },
    R: { path: "C:\\", items: [], index: 0, marked: {} },
  };

  function setStatus(t) { statusEl.textContent = t || ""; }
  function otherSide(side) { return side === "L" ? "R" : "L"; }

  function joinPath(base, name) {
    if (!base) return name;
    const sep = base.indexOf("/") >= 0 && base.indexOf("\\") < 0 ? "/" : "\\";
    if (base.endsWith("\\") || base.endsWith("/")) return base + name;
    return base + sep + name;
  }

  function parentPath(path) {
    let p = String(path || "").replace(/[\\\/]+$/, "");
    const i = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
    if (i > 0) return p.slice(0, i + 1);
    if (/^[A-Za-z]:/.test(p)) return p.slice(0, 2) + "\\";
    return path;
  }

  function fmtSize(n, isDir) {
    if (isDir) return "<DIR>";
    n = Number(n) || 0;
    if (n < 1024) return String(n);
    if (n < 1048576) return (n / 1024).toFixed(0) + "K";
    return (n / 1048576).toFixed(1) + "M";
  }

  function fmtDate(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yy = String(d.getFullYear()).slice(-2);
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return dd + "." + mm + "." + yy + " " + hh + ":" + mi;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function api(cmd, body) {
    return fetch("/api/files/" + encodeURIComponent(HOST) + "/" + cmd, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json(); });
  }

  // ——— Progress window (classic VC style) ———
  const progressModal = document.getElementById("progressModal");
  const progTitle = document.getElementById("progTitle");
  const progFile = document.getElementById("progFile");
  const progBar = document.getElementById("progBar");
  const progPct = document.getElementById("progPct");
  const progExtra = document.getElementById("progExtra");

  function showProgress(title, fileName) {
    progTitle.textContent = title || "Copy";
    progFile.textContent = fileName || "";
    progExtra.textContent = "";
    setProgress(0);
    progressModal.classList.add("show");
  }
  function setProgress(pct, extra) {
    pct = Math.max(0, Math.min(100, Math.round(pct)));
    progBar.style.width = pct + "%";
    progPct.textContent = pct + "%";
    if (extra != null) progExtra.textContent = extra;
  }
  function hideProgress() {
    progressModal.classList.remove("show");
  }

  // ——— Dialog ———
  const modal = document.getElementById("modal");
  const dlgTitle = document.getElementById("dlgTitle");
  const dlgText = document.getElementById("dlgText");
  const dlgInput = document.getElementById("dlgInput");
  let dlgResolve = null;

  function dialog(title, text, defaultVal, showInput) {
    return new Promise(function (resolve) {
      dlgResolve = resolve;
      dlgTitle.textContent = title;
      dlgText.textContent = text || "";
      dlgInput.style.display = showInput ? "block" : "none";
      dlgInput.value = defaultVal || "";
      modal.classList.add("show");
      if (showInput) setTimeout(function () { dlgInput.focus(); dlgInput.select(); }, 30);
    });
  }
  function closeDlg(ok) {
    modal.classList.remove("show");
    const v = dlgInput.value;
    const r = dlgResolve;
    dlgResolve = null;
    if (r) r(ok ? (dlgInput.style.display === "none" ? true : v) : null);
  }
  document.getElementById("dlgOk").onclick = function () { closeDlg(true); };
  document.getElementById("dlgCancel").onclick = function () { closeDlg(false); };
  dlgInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); closeDlg(true); }
    if (e.key === "Escape") { e.preventDefault(); closeDlg(false); }
  });

  function selected(side) {
    const st = S[side];
    if (st.index <= 0) return { name: "..", is_dir: true, is_up: true };
    return st.items[st.index - 1] || null;
  }

  function markedOrSelected(side) {
    const st = S[side];
    const names = Object.keys(st.marked);
    if (names.length) {
      return names.map(function (n) {
        return st.items.find(function (it) { return it.name === n; }) || { name: n, is_dir: false };
      });
    }
    const sel = selected(side);
    if (!sel || sel.is_up) return [];
    return [sel];
  }

  function render(side) {
    const st = S[side];
    document.getElementById("head-" + side).textContent = st.path;
    const list = document.getElementById("list-" + side);
    list.innerHTML = "";
    const rows = [{ name: "..", is_dir: true, is_up: true, size: 0, mtime: 0 }].concat(st.items || []);
    rows.forEach(function (item, i) {
      const row = document.createElement("div");
      const isSel = i === st.index;
      const isMarked = !item.is_up && !!st.marked[item.name];
      row.className = "row " + (item.is_dir ? "dir" : "file") + (isSel ? " sel" : "") + (isMarked ? " marked" : "");
      row.innerHTML =
        '<span class="n">' + escapeHtml(item.name) + "</span>" +
        '<span class="sz">' + fmtSize(item.size, item.is_dir) + "</span>" +
        '<span class="dt">' + (item.is_up ? "" : fmtDate(item.mtime)) + "</span>";
      row.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        setActive(side);
        const now = Date.now();
        const dbl = S.lastClick.side === side && S.lastClick.index === i && now - S.lastClick.time < 450;
        st.index = i;
        if (dbl) {
          S.lastClick = { side: null, index: -1, time: 0 };
          render(side);
          enter(side);
          return;
        }
        S.lastClick = { side: side, index: i, time: now };
        render(side);
      });
      list.appendChild(row);
    });
    const sel = selected(side);
    const markCount = Object.keys(st.marked).length;
    document.getElementById("foot-" + side).textContent =
      (markCount ? ("*" + markCount + " ") : "") + (sel ? sel.name : "");
    if (side === S.active) cmdPrompt.textContent = st.path + ">";
  }

  function setActive(side) {
    S.active = side;
    document.getElementById("panel-L").classList.toggle("active", side === "L");
    document.getElementById("panel-R").classList.toggle("active", side === "R");
    cmdPrompt.textContent = S[side].path + ">";
  }

  async function load(side, path) {
    setStatus("Reading " + path + " ...");
    const data = await api("list", { path: path });
    if (!data.ok) {
      setStatus("Error: " + (data.error || "fail"));
      return;
    }
    S[side].path = data.path;
    S[side].items = data.items || [];
    S[side].index = 0;
    S[side].marked = {};
    render(side);
    setStatus(data.path + "  " + S[side].items.length + " file(s)");
  }

  async function enter(side) {
    const st = S[side];
    const sel = selected(side);
    if (!sel) return;
    if (sel.is_up) { await load(side, parentPath(st.path)); return; }
    if (sel.is_dir) { await load(side, joinPath(st.path, sel.name)); return; }
    await viewFile(side);
  }

  function toggleMark(side) {
    const st = S[side];
    const sel = selected(side);
    if (!sel || sel.is_up) return;
    if (st.marked[sel.name]) delete st.marked[sel.name];
    else st.marked[sel.name] = true;
    st.index = Math.min((st.items || []).length, st.index + 1);
    render(side);
  }

  async function pickDrive(side) {
    setActive(side);
    if (!S.drives.length) {
      const data = await api("drives", {});
      S.drives = (data && data.drives) || ["C:\\"];
    }
    const val = await dialog(
      "Drive",
      "Диски: " + S.drives.join("  ") + "\n\nВведите путь:",
      S[side].path,
      true
    );
    if (val == null || !String(val).trim()) return;
    await load(side, String(val).trim());
  }

  document.getElementById("head-L").addEventListener("click", function (e) {
    e.stopPropagation(); pickDrive("L");
  });
  document.getElementById("head-R").addEventListener("click", function (e) {
    e.stopPropagation(); pickDrive("R");
  });

  async function viewFile(side) {
    const sel = selected(side || S.active);
    if (!sel || sel.is_dir || sel.is_up) { setStatus("Select a file"); return; }
    setStatus("Loading...");
    const path = joinPath(S[side || S.active].path, sel.name);
    const data = await api("download", { path: path });
    if (!data.ok) { setStatus("Error: " + data.error); return; }
    try {
      const bin = atob(data.data_b64);
      let text = "";
      for (let i = 0; i < Math.min(bin.length, 4000); i++) {
        const c = bin.charCodeAt(i);
        text += (c >= 32 && c < 127) || c > 159 || c === 10 || c === 13 || c === 9 ? bin.charAt(i) : ".";
      }
      await dialog("View — " + sel.name, text, "", false);
      closeDlg(true);
    } catch (err) {
      setStatus("Cannot view file");
    }
  }

  // ——— F5 Copy remote → remote (with progress window) ———
  async function fCopy() {
    const side = S.active;
    const items = markedOrSelected(side);
    if (!items.length) return;
    const dstDir = S[otherSide(side)].path;
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const src = joinPath(S[side].path, it.name);
      let dst = joinPath(dstDir, it.name);
      if (items.length === 1) {
        const v = await dialog("Copy", "Copy to:", dst, true);
        if (v == null) return;
        dst = v;
      }
      showProgress("Copy", src + "\n→ " + dst);
      setProgress(5, "Remote copy...");
      // animate while waiting
      let p = 5;
      const timer = setInterval(function () {
        p = Math.min(90, p + 3);
        setProgress(p);
      }, 200);
      const data = await api("copy", { path: src, new_path: dst });
      clearInterval(timer);
      if (!data.ok) {
        setProgress(100, "Error: " + data.error);
        await sleep(900);
        hideProgress();
        setStatus("Error: " + data.error);
        return;
      }
      setProgress(100, "Done");
      await sleep(350);
    }
    hideProgress();
    S[side].marked = {};
    setStatus("Copy OK");
    await load("L", S.L.path);
    await load("R", S.R.path);
  }

  // ——— F4 Get: remote → this PC (browser download) ———
  async function fGet() {
    const side = S.active;
    const items = markedOrSelected(side).filter(function (x) { return !x.is_dir && !x.is_up; });
    if (!items.length) {
      setStatus("Select file(s) to download to this PC");
      return;
    }
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const path = joinPath(S[side].path, it.name);
      showProgress("Get → This PC", path);
      setProgress(10, "Downloading from remote...");
      let p = 10;
      const timer = setInterval(function () {
        p = Math.min(85, p + 2);
        setProgress(p);
      }, 150);
      const data = await api("download", { path: path });
      clearInterval(timer);
      if (!data.ok) {
        setProgress(100, "Error: " + data.error);
        await sleep(900);
        hideProgress();
        setStatus("Error: " + data.error);
        return;
      }
      setProgress(92, "Saving on this PC...");
      try {
        const bin = atob(data.data_b64);
        const arr = new Uint8Array(bin.length);
        for (let j = 0; j < bin.length; j++) arr[j] = bin.charCodeAt(j);
        const blob = new Blob([arr]);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = data.name || it.name;
        a.click();
        URL.revokeObjectURL(a.href);
        setProgress(100, "Saved: " + a.download);
        await sleep(400);
      } catch (err) {
        setProgress(100, "Save error");
        await sleep(800);
        hideProgress();
        setStatus("Save error");
        return;
      }
    }
    hideProgress();
    setStatus("Download to this PC complete");
  }

  // ——— F9 Put: this PC → remote (upload) ———
  function fPut() {
    fileInput.value = "";
    fileInput.click();
  }

  fileInput.addEventListener("change", async function (e) {
    const files = e.target.files;
    if (!files || !files.length) return;
    const destDir = S[S.active].path;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const dest = joinPath(destDir, file.name);
      showProgress("Put ← This PC", file.name + "\n→ " + dest);
      setProgress(0, "Reading local file...");
      let b64;
      try {
        b64 = await readFileAsBase64(file, function (pct) {
          setProgress(Math.round(pct * 0.4), "Reading " + Math.round(pct) + "%");
        });
      } catch (err) {
        setProgress(100, "Read error");
        await sleep(800);
        hideProgress();
        return;
      }
      setProgress(45, "Uploading to remote...");
      const data = await uploadWithProgress(dest, b64, function (pct) {
        setProgress(45 + Math.round(pct * 0.5), "Upload " + Math.round(pct) + "%");
      });
      if (!data.ok) {
        setProgress(100, "Error: " + (data.error || "upload failed"));
        await sleep(1000);
        hideProgress();
        setStatus("Error: " + data.error);
        return;
      }
      setProgress(100, "Done");
      await sleep(350);
    }
    hideProgress();
    setStatus("Upload complete");
    await load("L", S.L.path);
    await load("R", S.R.path);
    fileInput.value = "";
  });

  function readFileAsBase64(file, onProg) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onprogress = function (ev) {
        if (ev.lengthComputable && onProg) onProg((ev.loaded / ev.total) * 100);
      };
      reader.onload = function () {
        const dataUrl = reader.result; // data:...;base64,XXXX
        const i = String(dataUrl).indexOf("base64,");
        resolve(i >= 0 ? dataUrl.slice(i + 7) : "");
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function uploadWithProgress(path, data_b64, onProg) {
    return new Promise(function (resolve) {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/files/" + encodeURIComponent(HOST) + "/upload");
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.withCredentials = true;
      xhr.upload.onprogress = function (ev) {
        if (ev.lengthComputable && onProg) onProg((ev.loaded / ev.total) * 100);
      };
      xhr.onload = function () {
        try { resolve(JSON.parse(xhr.responseText)); }
        catch (e) { resolve({ ok: false, error: "bad response" }); }
      };
      xhr.onerror = function () { resolve({ ok: false, error: "network" }); };
      xhr.send(JSON.stringify({ path: path, data_b64: data_b64 }));
    });
  }

  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  async function fRenMov() {
    const side = S.active;
    const sel = selected(side);
    if (!sel || sel.is_up) return;
    const src = joinPath(S[side].path, sel.name);
    const choice = await dialog("RenMov", "New name or full path:", joinPath(S[otherSide(side)].path, sel.name), true);
    if (choice == null) return;
    showProgress("RenMov", src + "\n→ " + choice);
    setProgress(30);
    const data = await api("move", { path: src, new_path: choice });
    setProgress(100, data.ok ? "Done" : data.error);
    await sleep(400);
    hideProgress();
    setStatus(data.ok ? "OK" : "Error: " + data.error);
    await load("L", S.L.path);
    await load("R", S.R.path);
  }

  async function fMkDir() {
    const name = await dialog("Make directory", "Directory name:", "NEWDIR", true);
    if (name == null || !String(name).trim()) return;
    const path = joinPath(S[S.active].path, String(name).trim());
    const data = await api("mkdir", { path: path });
    setStatus(data.ok ? "Directory created" : "Error: " + data.error);
    await load(S.active, S[S.active].path);
  }

  async function fDelete() {
    const side = S.active;
    const items = markedOrSelected(side);
    if (!items.length) return;
    const names = items.map(function (x) { return x.name; }).join(", ");
    const ok = await dialog("Delete", "Delete " + names + " ?", "", false);
    if (ok == null) return;
    closeDlg(true);
    for (let i = 0; i < items.length; i++) {
      showProgress("Delete", items[i].name);
      setProgress(40);
      const data = await api("delete", { path: joinPath(S[side].path, items[i].name) });
      setProgress(100, data.ok ? "Done" : data.error);
      await sleep(250);
      if (!data.ok) {
        hideProgress();
        setStatus("Error: " + data.error);
        return;
      }
    }
    hideProgress();
    S[side].marked = {};
    setStatus("Deleted");
    await load(side, S[side].path);
  }

  async function fInfo() {
    const sel = selected(S.active);
    if (!sel || sel.is_up) return;
    await dialog("Info", joinPath(S[S.active].path, sel.name) + "\n" + (sel.is_dir ? "Directory" : "Size: " + sel.size), "", false);
    closeDlg(true);
  }

  async function fHelp() {
    await dialog(
      "Help",
      "F4 Get↓  — download remote file → THIS PC\n" +
      "F9 Put↑  — upload from THIS PC → remote\n" +
      "F5 Copy  — copy on remote (panel → panel)\n" +
      "Space — mark yellow   Enter/dbl-click — open\n" +
      "Click path header — change drive\n" +
      "F10 Quit",
      "",
      false
    );
    closeDlg(true);
  }

  function fQuit() { window.location.href = "/"; }

  const actions = {
    1: fHelp, 2: fInfo, 3: function () { return viewFile(S.active); },
    4: fGet, 5: fCopy, 6: fRenMov, 7: fMkDir, 8: fDelete, 9: fPut, 10: fQuit,
  };

  document.querySelectorAll(".fn").forEach(function (el) {
    el.addEventListener("click", function () {
      const n = parseInt(el.getAttribute("data-f"), 10);
      if (actions[n]) actions[n]();
    });
  });

  document.addEventListener("keydown", function (e) {
    if (modal.classList.contains("show") || progressModal.classList.contains("show")) {
      if (e.key === "Escape" && modal.classList.contains("show")) closeDlg(false);
      return;
    }
    if (document.activeElement === cmdInput) {
      if (e.key === "Escape") cmdInput.blur();
      return;
    }
    const side = S.active;
    const st = S[side];
    const max = (st.items || []).length;
    if (e.key === "Tab") { e.preventDefault(); setActive(otherSide(side)); render(S.active); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); st.index = Math.min(max, st.index + 1); render(side); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); st.index = Math.max(0, st.index - 1); render(side); return; }
    if (e.key === "Enter") { e.preventDefault(); enter(side); return; }
    if (e.key === " " || e.code === "Space") { e.preventDefault(); toggleMark(side); return; }
    if (e.key === "Insert") { e.preventDefault(); toggleMark(side); return; }
    if (e.key === "Backspace") { e.preventDefault(); load(side, parentPath(st.path)); return; }
    const fMatch = e.key.match(/^F(\d{1,2})$/);
    if (fMatch) {
      e.preventDefault();
      const n = parseInt(fMatch[1], 10);
      if (actions[n]) actions[n]();
    }
  });

  document.getElementById("panel-L").addEventListener("mousedown", function () { setActive("L"); });
  document.getElementById("panel-R").addEventListener("mousedown", function () { setActive("R"); });

  cmdInput.addEventListener("keydown", async function (e) {
    if (e.key !== "Enter") return;
    const v = cmdInput.value.trim();
    if (!v) return;
    if (/^[A-Za-z]:/.test(v) || v.indexOf("\\") >= 0 || v.indexOf("/") >= 0) {
      await load(S.active, v);
      cmdInput.value = "";
    }
  });

  api("drives", {}).then(function (data) {
    S.drives = (data && data.drives) || ["C:\\"];
  });
  load("L", "C:\\");
  load("R", "C:\\");
})();

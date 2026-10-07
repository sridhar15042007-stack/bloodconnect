/* =====================================================================
   BloodConnect front-end
   One page (index.html), hash routing (#/search, #/login ...),
   data comes from the JSON API in app.py
   ===================================================================== */

// Google Maps JavaScript API key. Restrict it by HTTP referrer in Google Cloud.
const GOOGLE_MAPS_KEY = "AIzaSyBfYhwgI6ZNrf0kuvNRAm_SIDd5jsyIcTM";

const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];
const DEFAULT_CENTER = { lat: 13.0827, lng: 80.2707 }; // Chennai

const SPLASH_MS = 2800;  // how long the logo page stays before moving to Sign In

const state = { user: null, page: "", tab: "in" };
let mapsReady = false;
let pendingMap = null;
let splashTimer = null;
let splashSeen = false;


/* ---------------------------------------------------------------------
   Helpers
   --------------------------------------------------------------------- */
const $  = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

// Escape user text before putting it into innerHTML (prevents XSS).
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError("Cannot reach the server. Is app.py running?", 0);
  }
  let data = {};
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) throw new ApiError(data.error || "Something went wrong.", response.status);
  return data;
}

function flash(message, type = "success") {
  const box = document.createElement("div");
  box.className = "flash " + type;
  box.textContent = message;
  $("#flash").appendChild(box);
  setTimeout(() => box.remove(), 3500);
}

function navigate(hash) {
  if (location.hash === hash) router();   // same hash fires no event, so refresh by hand
  else location.hash = hash;
}

const formData = (form) => Object.fromEntries(new FormData(form));


/* ---------------------------------------------------------------------
   Navbar + page switching
   --------------------------------------------------------------------- */
function renderNav() {
  const u = state.user;
  const p = state.page;
  const link = (href, label, active) =>
    `<a href="${href}"${active ? ' class="active"' : ""}>${label}</a>`;

  let html = link("#/home", "Home", p === "home")
           + link("#/search", "Find Donor", p === "search")
           + link("#/request", "Blood Request", p === "request");

  if (u) {
    html += link("#/dashboard", "Dashboard", p === "profile" || p === "admin")
          + link("#/logout", "Logout", false);
  } else {
    html += link("#/login", "Sign In", p === "sign" && state.tab === "in")
          + '<a class="navbtn" href="#/register">Sign Up</a>';
  }
  $("#navlinks").innerHTML = html;
}

function showPage(name) {
  state.page = name;
  if (name !== "splash") clearTimeout(splashTimer);
  document.body.classList.toggle("is-splash", name === "splash");  // hides navbar + footer
  $$(".page").forEach((p) => { p.hidden = p.id !== "page-" + name; });
  renderNav();
}


/* ---------------------------------------------------------------------
   HTML snippets
   --------------------------------------------------------------------- */
const donorCardHome = (d) => `
  <div class="card donor-card">
    <div class="avatar">👤</div>
    <div><h3>${esc(d.name)}</h3><p>${esc(d.city)}</p></div>
    <strong class="blood">${esc(d.blood_group)}</strong>
    <span class="status">● Available</span>
  </div>`;

const donorCardSearch = (d) => `
  <div class="card donor-card">
    <div class="avatar">🩸</div>
    <div><h3>${esc(d.name)}</h3><p>${esc(d.city)}</p><p>📞 ${esc(d.phone)}</p></div>
    <strong class="blood">${esc(d.blood_group)}</strong>
    <span class="status">● Available</span>
  </div>`;

const requestRow = (r) => `
  <a class="request-link" href="#/request/${Number(r.id)}">
    <div class="request-row">
      <div><b>${esc(r.blood_group)} • ${esc(r.units)} unit(s)</b><br><small>${esc(r.hospital)}, ${esc(r.city)}</small></div>
      <span class="tag ${esc(r.urgency.toLowerCase())}">${esc(r.urgency)}</span>
    </div>
  </a>`;

function adminActions(r) {
  const btn = (status, label) =>
    `<button class="link-btn" data-id="${Number(r.id)}" data-status="${status}">${label}</button>`;
  if (r.status === "Pending")  return btn("Approved", "Approve") + '<span class="sep">|</span>' + btn("Rejected", "Reject");
  if (r.status === "Approved") return btn("Completed", "Complete");
  return "—";
}


/* ---------------------------------------------------------------------
   Google Maps
   --------------------------------------------------------------------- */
function loadGoogleMaps() {
  if (!GOOGLE_MAPS_KEY) return;
  window.initGoogleMaps = () => {
    mapsReady = true;
    if (pendingMap) pendingMap();
    pendingMap = null;
  };
  const script = document.createElement("script");
  script.src = `https://maps.googleapis.com/maps/api/js?key=${GOOGLE_MAPS_KEY}&callback=initGoogleMaps`;
  script.async = true;
  script.onerror = () => $$("#map, #requester-map").forEach((el) => { el.textContent = "Map unavailable."; });
  document.head.appendChild(script);
}

function whenMapsReady(fn) {
  if (mapsReady) fn();
  else pendingMap = fn;
}

function renderRequestsMap(cities) {
  whenMapsReady(() => {
    if (state.page !== "home") return;
    const map = new google.maps.Map($("#map"), { center: DEFAULT_CENTER, zoom: 11, streetViewControl: false });
    if (!cities.length) {
      new google.maps.Marker({ map, position: DEFAULT_CENTER, title: "BloodConnect - Chennai" });
      return;
    }
    const geocoder = new google.maps.Geocoder();
    cities.forEach((city, index) => {
      geocoder.geocode({ address: city + ", India" }, (results, status) => {
        if (status !== "OK" || !results[0]) return;
        const position = results[0].geometry.location;
        new google.maps.Marker({ map, position, title: `Blood Request #${index + 1} - ${city}` });
        if (index === 0) { map.setCenter(position); map.setZoom(12); }
      });
    });
  });
}

function renderRequesterMap(city, title) {
  whenMapsReady(() => {
    if (state.page !== "request-details") return;
    const map = new google.maps.Map($("#requester-map"), { center: DEFAULT_CENTER, zoom: 12, streetViewControl: false });
    new google.maps.Geocoder().geocode({ address: city + ", India" }, (results, status) => {
      if (status !== "OK" || !results[0]) return;
      const position = results[0].geometry.location;
      map.setCenter(position);
      map.setZoom(14);
      const marker = new google.maps.Marker({ map, position, title });
      new google.maps.InfoWindow({ content: `<b>${esc(title)}</b><br>${esc(city)}` }).open({ anchor: marker, map });
    });
  });
}


/* ---------------------------------------------------------------------
   Pages
   --------------------------------------------------------------------- */
async function showHome() {
  showPage("home");
  const { donors, requests } = await api("/api/home");
  $("#home-donors").innerHTML =
    donors.map(donorCardHome).join("") || '<div class="empty">No donors available yet. Be the first donor!</div>';
  $("#home-requests").innerHTML =
    requests.map(requestRow).join("") || '<p class="muted">No requests yet.</p>';
  renderRequestsMap(requests.map((r) => r.city));
}

async function showSearch(params) {
  showPage("search");
  const blood = params.get("blood_group") || "";
  const city = params.get("city") || "";
  const form = $("#search-form");
  form.blood_group.value = blood;
  form.city.value = city;

  const { donors } = await api("/api/search?" + new URLSearchParams({ blood_group: blood, city }));
  $("#search-results").innerHTML =
    donors.map(donorCardSearch).join("") || '<div class="empty">No matching available donors found.</div>';
}

function showRequestForm() {
  showPage("request");
}

async function showRequestDetails(id) {
  if (!/^\d+$/.test(id)) {
    flash("Blood request not found.", "error");
    return navigate("#/home");
  }
  showPage("request-details");
  $("#request-details").innerHTML = "";
  let r;
  try {
    ({ request: r } = await api("/api/request/" + id));
  } catch (err) {
    if (err.status === 404) {
      flash("Blood request not found.", "error");
      return navigate("#/home");
    }
    throw err;
  }
  const row = (label, value) => `<p><b>${label}</b><span>${value}</span></p>`;
  $("#request-details").innerHTML = `
    <span class="badge">Blood Request #${Number(r.id)}</span>
    <h1>${esc(r.blood_group)} Blood Required</h1>
    <p class="muted">Requester details</p>
    <div class="detail-list">
      ${row("Requester", esc(r.requester_name))}
      ${row("Phone", esc(r.phone))}
      ${row("Blood Group", `<span class="blood">${esc(r.blood_group)}</span>`)}
      ${row("Units", esc(r.units))}
      ${row("Hospital", esc(r.hospital))}
      ${row("Location", esc(r.city))}
      ${row("Urgency", esc(r.urgency))}
      ${row("Status", esc(r.status))}
    </div>
    <a class="btn" href="tel:${esc(r.phone)}">📞 Contact Requester</a>`;
  renderRequesterMap(r.city, "Blood Requester");
}

/* Page 1: the logo (splash). Moves on to Sign In by itself, or when "Get Started" is clicked. */
function showStart() {
  if (state.user) return navigate("#/dashboard");   // already signed in, skip the logo page
  showPage("splash");
  $("#page-splash").classList.toggle("no-auto", splashSeen);   // only auto-advance the first time
  if (!splashSeen) {
    splashTimer = setTimeout(() => {
      if (state.page === "splash") navigate("#/login");
    }, SPLASH_MS);
  }
  splashSeen = true;
}

/* Page 2: Sign In / Sign Up (one page, two tabs) */
function showSign(tab) {
  state.tab = tab;
  showPage("sign");
  $("#tab-in").classList.toggle("active", tab === "in");
  $("#tab-up").classList.toggle("active", tab === "up");
  $("#login-form").hidden = tab !== "in";
  $("#register-form").hidden = tab !== "up";
}

const showLogin = () => showSign("in");
const showRegister = () => showSign("up");

/* Page 3: Dashboard (admin dashboard for admins, donor dashboard for everyone else) */
function showDashboard() {
  if (!state.user) return navigate("#/login");
  return state.user.role === "admin" ? showAdmin() : showProfile();
}

async function showProfile() {
  if (!state.user) return navigate("#/login");
  showPage("profile");
  const { user, donor } = await api("/api/profile");
  let html = `<h1>Hello, ${esc(user.name)} 👋</h1><p class="muted">Your donor dashboard</p>`;
  if (donor) {
    const available = donor.availability === "Available";
    html += `
      <div class="profile-grid">
        <div class="card">
          <h3>Donor Details</h3>
          <p><b>Email:</b> ${esc(user.email)}</p>
          <p><b>Phone:</b> ${esc(donor.phone)}</p>
          <p><b>Blood Group:</b> <span class="blood">${esc(donor.blood_group)}</span></p>
          <p><b>Location:</b> ${esc(donor.city)}</p>
        </div>
        <div class="card">
          <h3>Availability</h3>
          <div class="availability${available ? "" : " off"}">${esc(donor.availability)}</div>
          <button class="btn" id="toggle-availability">${available ? "Mark Not Available" : "Mark Available"}</button>
        </div>
      </div>`;
  } else {
    html += `<div class="card"><p><b>Email:</b> ${esc(user.email)}</p><p class="muted">This account has no donor profile.</p></div>`;
  }
  html += `
    <h2 class="dash-h">Quick actions</h2>
    <div class="grid">
      <a class="card action-card" href="#/search"><span>🔎</span><b>Find a Donor</b><small class="muted">Search by blood group and city</small></a>
      <a class="card action-card" href="#/request"><span>🩸</span><b>Request Blood</b><small class="muted">Submit an emergency request</small></a>
      <a class="card action-card" href="#/home"><span>🏠</span><b>Home</b><small class="muted">Recent requests and map</small></a>
    </div>`;
  $("#profile-content").innerHTML = html;
}

async function showAdmin() {
  if (state.user?.role !== "admin") return navigate("#/login");
  showPage("admin");
  const { stats, donors, requests } = await api("/api/admin");

  const stat = (n, label) => `<div class="stat"><b>${Number(n)}</b><span>${label}</span></div>`;
  $("#admin-stats").innerHTML =
    stat(stats.donors, "Total Donors") + stat(stats.available, "Available") +
    stat(stats.requests, "Requests") + stat(stats.pending, "Pending");

  $("#admin-requests").innerHTML = requests.map((r) => `
    <tr>
      <td>#${Number(r.id)}</td><td>${esc(r.requester_name)}</td><td><b>${esc(r.blood_group)}</b></td>
      <td>${esc(r.hospital)}</td><td>${esc(r.city)}</td><td>${esc(r.urgency)}</td>
      <td>${esc(r.status)}</td><td>${adminActions(r)}</td>
    </tr>`).join("") || '<tr><td colspan="8" class="muted">No requests yet.</td></tr>';

  $("#admin-donors").innerHTML = donors.map((d) => `
    <tr>
      <td>${esc(d.name)}</td><td><b>${esc(d.blood_group)}</b></td><td>${esc(d.phone)}</td>
      <td>${esc(d.city)}</td><td>${esc(d.availability)}</td>
    </tr>`).join("") || '<tr><td colspan="5" class="muted">No donors yet.</td></tr>';
}

function showLogo() {
  showPage("logo");
}

async function doLogout() {
  await api("/api/logout", { method: "POST" });
  state.user = null;
  navigate("#/login");
}


/* ---------------------------------------------------------------------
   Router
   --------------------------------------------------------------------- */
const routes = {
  "": showStart,          // page 1: logo
  login: showLogin,       // page 2: sign in
  register: showRegister, //         sign up
  dashboard: showDashboard, // page 3
  home: showHome,
  search: showSearch,
  request: showRequestForm,
  profile: showProfile,
  admin: showAdmin,
  logo: showLogo,
  logout: doLogout,
};

async function router() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const [name = "", arg] = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);

  window.scrollTo(0, 0);
  try {
    if (name === "request" && arg) await showRequestDetails(arg);
    else if (routes[name]) await routes[name](params);
    else showPage("notfound");
  } catch (err) {
    if (err.status === 401 || err.status === 403) {
      if (err.status === 401) state.user = null;
      renderNav();
      flash(err.message, "error");
      navigate("#/login");
    } else {
      flash(err.message || "Something went wrong.", "error");
    }
  }
}


/* ---------------------------------------------------------------------
   Forms and buttons
   --------------------------------------------------------------------- */
function fillBloodSelects() {
  $$("select[data-blood]").forEach((select) => {
    const first = `<option value="">${esc(select.dataset.placeholder || "Select")}</option>`;
    select.innerHTML = first + BLOOD_GROUPS.map((g) => `<option>${g}</option>`).join("");
  });
}

function bindEvents() {
  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const { blood_group, city } = formData(e.target);
    navigate("#/search?" + new URLSearchParams({ blood_group, city: city.trim() }));
  });

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const { user } = await api("/api/login", { method: "POST", body: formData(e.target) });
      state.user = user;
      e.target.reset();
      flash("Signed in as " + user.name + ".");
      navigate("#/dashboard");
    } catch (err) {
      flash(err.message, "error");
    }
  });

  $("#register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/register", { method: "POST", body: formData(e.target) });
      e.target.reset();
      flash("Registration successful. Please sign in.");
      navigate("#/login");
    } catch (err) {
      flash(err.message, "error");
    }
  });

  $("#request-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/request-blood", { method: "POST", body: formData(e.target) });
      e.target.reset();
      flash("Blood request submitted successfully.");
      navigate("#/home");
    } catch (err) {
      flash(err.message, "error");
    }
  });

  // Profile: availability toggle
  $("#profile-content").addEventListener("click", async (e) => {
    if (!e.target.closest("#toggle-availability")) return;
    try {
      await api("/api/toggle-availability", { method: "POST" });
      await showProfile();
    } catch (err) {
      flash(err.message, "error");
    }
  });

  // Admin: approve / reject / complete
  $("#admin-requests").addEventListener("click", async (e) => {
    const button = e.target.closest("[data-status]");
    if (!button) return;
    button.disabled = true;
    try {
      await api(`/api/admin/request/${button.dataset.id}/${button.dataset.status}`, { method: "POST" });
      await showAdmin();
    } catch (err) {
      flash(err.message, "error");
      button.disabled = false;
    }
  });

  // Logo page: download an inline logo as an .svg file
  $("#page-logo").addEventListener("click", (e) => {
    const button = e.target.closest("[data-download]");
    if (!button) return;
    const svg = document.getElementById(button.dataset.source).cloneNode(true);
    svg.removeAttribute("id");
    svg.removeAttribute("class");
    const blob = new Blob([svg.outerHTML], { type: "image/svg+xml" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = button.dataset.download;
    link.click();
    URL.revokeObjectURL(link.href);
  });

  window.addEventListener("hashchange", router);
}


/* ---------------------------------------------------------------------
   Start
   --------------------------------------------------------------------- */
async function init() {
  fillBloodSelects();
  bindEvents();
  loadGoogleMaps();
  try {
    state.user = (await api("/api/me")).user;
  } catch {
    state.user = null;
  }
  router();
}

init();

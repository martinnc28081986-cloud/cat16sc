// Firebase de mentira, en memoria, para probar index.html sin credenciales.
const seed = await (await fetch('/seed.json' + location.search)).json();
const tree = seed;
window.__fbdb = tree;
window.__writes = [];

const parts = p => String(p || '').split('/').filter(Boolean);
const clone = v => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
function getAt(path) {
  let n = tree;
  for (const k of parts(path)) {
    if (n == null || typeof n !== 'object') return null;
    n = n[k];
  }
  return n === undefined ? null : n;
}
function setAt(path, val) {
  const ks = parts(path);
  if (!ks.length) throw new Error('root write');
  let n = tree;
  for (let i = 0; i < ks.length - 1; i++) {
    if (n[ks[i]] == null || typeof n[ks[i]] !== 'object') n[ks[i]] = {};
    n = n[ks[i]];
  }
  const last = ks[ks.length - 1];
  if (val === null || val === undefined) delete n[last];
  else n[last] = clone(val);
}
// Firebase borra los null anidados
function strip(v) {
  if (v && typeof v === 'object') {
    for (const k of Object.keys(v)) { if (v[k] === null || v[k] === undefined) delete v[k]; else strip(v[k]); }
  }
  return v;
}
const listeners = [];
function notify(path) {
  const w = parts(path).join('/');
  listeners.slice().forEach(l => {
    const lp = parts(l.path).join('/');
    if (lp === w || lp.startsWith(w + '/') || w.startsWith(lp + '/')) setTimeout(() => l.fire(), 0);
  });
}
function snap(path, val) {
  const key = parts(path).pop() || null;
  return {
    key,
    val: () => clone(val),
    exists: () => val !== null && val !== undefined,
    forEach: cb => {
      if (val && typeof val === 'object') {
        for (const k of Object.keys(val)) if (cb(snap(path + '/' + k, val[k])) === true) return true;
      }
      return false;
    },
  };
}
export const initializeApp = () => ({});
export const getDatabase = () => ({});
export const ref = (db, path) => ({ path: parts(path).join('/'), key: parts(path).pop() || null });
const LAT = +(new URLSearchParams(location.search).get('lat')||0);
window.__log = [];
const espera = () => LAT ? new Promise(r => setTimeout(r, LAT)) : null;
const leerQ = r => { let v = getAt(r.path); const c = r.cons || []; if (v && typeof v === 'object' && c.some(x => x && x.t === 'key')) { const st = (c.find(x => x && x.t === 'start') || {}).v, en = (c.find(x => x && x.t === 'end') || {}).v; v = Object.fromEntries(Object.entries(v).filter(([k]) => (st === undefined || k >= st) && (en === undefined || k <= en))); if (!Object.keys(v).length) v = null; } return v; };
export const get = async r => { window.__log.push(['get', r.path + (r.cons ? '?q' : ''), Date.now()]); const e = espera(); if(e) await e; return snap(r.path, leerQ(r)); };
const res = (path, v) => (v && typeof v === 'object' && v.__inc !== undefined) ? ((+getAt(path) || 0) + v.__inc) : v;
export const increment = n => ({ __inc: n });
export const set = async (r, v) => { window.__writes.push(['set', r.path]); setAt(r.path, strip(clone(v))); notify(r.path); };
export const update = async (r, v) => {
  window.__writes.push(['update', r.path]);
  for (const [k, val] of Object.entries(v)) setAt(r.path + '/' + k, strip(clone(res(r.path + '/' + k, val))));
  notify(r.path);
};
export const remove = async r => { window.__writes.push(['remove', r.path]); setAt(r.path, null); notify(r.path); };
export const push = (r, v) => {
  const key = '-N' + Math.random().toString(36).slice(2, 10);
  const child = { path: r.path + '/' + key, key };
  const p = Promise.resolve(child);
  child.then = p.then.bind(p);
  if (v !== undefined) setAt(child.path, v);
  return child;
};
export const onValue = (r, cb, errCb) => {
  window.__log.push(['onValue', r.path, Date.now()]);
  const l = { path: r.path, fire: () => { const e = espera(); (e ? e : Promise.resolve()).then(() => cb(snap(r.path, leerQ(r)))); } };
  listeners.push(l);
  setTimeout(() => l.fire(), 0);
  return () => { const i = listeners.indexOf(l); if (i >= 0) listeners.splice(i, 1); };
};
export const onDisconnect = () => ({ remove: async () => {}, set: async () => {}, update: async () => {} });

const authObj = { currentUser: null };
let authCb = null;
export const getAuth = () => authObj;
export const onAuthStateChanged = (a, cb) => {
  authCb = cb;
  const as = new URLSearchParams(location.search).get('as');
  setTimeout(() => {
    if (as && tree.users && tree.users[as]) {
      authObj.currentUser = { uid: as, email: tree.users[as].email };
      cb(authObj.currentUser);
    } else cb(null);
  }, 0);
};
export const signOut = async () => { authObj.currentUser = null; if (authCb) authCb(null); };
export const signInWithEmailAndPassword = async () => { throw Object.assign(new Error('stub'), { code: 'auth/stub' }); };
export const createUserWithEmailAndPassword = signInWithEmailAndPassword;
export const sendPasswordResetEmail = async (a, email) => { (window.__resets = window.__resets || []).push(email); };
export const confirmPasswordReset = async () => {};
export const verifyPasswordResetCode = async () => { throw new Error('stub'); };
export const query = (r, ...cons) => ({ path: r.path, key: r.key, cons });
export const orderByChild = () => ({ t: 'child' });
export const orderByKey = () => ({ t: 'key' });
export const startAt = v => ({ t: 'start', v });
export const endAt = v => ({ t: 'end', v });

// ── Identity Toolkit de mentira (signUp / sendOobCode) ──
const cuentas = { 'orfano@x.com': 'ORF1', 'sa@x.com': 'SA', 'baja@x.com': 'BAJ1' };
let nuevas = 0;
window.__cuentas = cuentas; window.__oob = [];
const fetchReal = window.fetch.bind(window);
window.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('identitytoolkit.googleapis.com')) {
    const body = JSON.parse(opts.body);
    const json = o => new Response(JSON.stringify(o), { status: 200, headers: { 'content-type': 'application/json' } });
    if (u.includes('accounts:signUp')) {
      const e = body.email.toLowerCase();
      if (cuentas[e]) return json({ error: { message: 'EMAIL_EXISTS' } });
      cuentas[e] = 'NEW' + (++nuevas);
      return json({ localId: cuentas[e], email: e });
    }
    if (u.includes('sendOobCode')) { window.__oob.push(body.email); return json({ email: body.email }); }
  }
  return fetchReal(url, opts);
};

// ── contador de listeners activos (para detectar acumulación) ──
(function () {
  const activos = new Map(); // key -> Set(fn)
  const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
  const clave = (t, tipo) => (t === document ? 'document' : t === window ? 'window' : (t && t.id) || (t && t.nodeName) || 'otro') + ':' + tipo;
  EventTarget.prototype.addEventListener = function (tipo, fn, o) { if (typeof fn === 'function') { const k = clave(this, tipo); if (!activos.has(k)) activos.set(k, new Set()); activos.get(k).add(fn); } return add.call(this, tipo, fn, o); };
  EventTarget.prototype.removeEventListener = function (tipo, fn, o) { const k = clave(this, tipo); if (activos.has(k)) activos.get(k).delete(fn); return rem.call(this, tipo, fn, o); };
  window.__listeners = () => Object.fromEntries([...activos].filter(([k, s]) => /^(document|window|sessionDate):/.test(k)).map(([k, s]) => [k, s.size]));
})();

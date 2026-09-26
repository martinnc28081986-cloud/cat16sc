/* Servidor local del arnés de pruebas de MI PLANTEL.
   Sirve index.html cambiando los imports de Firebase por un Firebase simulado en memoria
   (fb-stub.js) y le carga datos de ejemplo de varios clubes con formas distintas (seed).
   Uso:  node tools/harness/server.js   →   http://localhost:8125/?as=PROFE
   Ver README.md. No usa credenciales ni toca datos reales. */
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');          // raíz del repositorio
const PORT = +process.env.PORT || 8125;
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css' };

/* ── DATOS DE EJEMPLO ─────────────────────────────────────────────────────
   Cada club representa una FORMA real de los datos, para probar que un cambio anda en todas:
   · clubA          club "completo" (fixture propio, dos temporadas, historial, motivos de no citación, uso)
   · hernandez      club con fixture y liga LISFI (RSVP activado en producción)
   · sagrado-corazon  el club histórico
   · clubB          club chico, una categoría
   · clubC          club NUEVO: sin fixture, con la categoría 2021 y la lista de categorías repetida
   Los usuarios BADROL, HUERFANO y SINCAT existen a propósito, para que el chequeo de salud tenga
   algo que marcar. */
function seed() {
  const P = ['Benja', 'Ciro', 'Feli', 'Mateo', 'Ramiro', 'Santi'];
  const players = {};
  const POSI = { Benja: 'arq', Ciro: 'def', Feli: 'med', Mateo: 'del' };
  P.forEach((n, i) => { players['p' + i] = Object.assign({ nombre: n, activo: true }, POSI[n] ? { pos: POSI[n] } : {}); });
  const mk = (fecha, rival, citados, fstr, extra) => Object.assign({ fecha, rival, condicion: 'L', citados, fecha_str: fstr, savedAt: fstr }, extra || {});
  // Zona anterior (z1): 3 partidos viejos, SIN noCitados (datos de antes de que existiera el motivo)
  const z1cit = {
    fecha01_rival_a: mk(1, 'RIVAL A', ['Benja', 'Ciro', 'Feli'], '2026-03-14'),
    fecha02_rival_b: mk(2, 'RIVAL B', ['Benja', 'Feli', 'Mateo'], '2026-03-21'),
    fecha03_rival_c: mk(3, 'RIVAL C', ['Benja', 'Ciro', 'Mateo', 'Santi'], '2026-03-28'),
  };
  const z1stats = {};
  Object.keys(z1cit).forEach(k => { z1stats[k] = { jugadores: {} }; z1cit[k].citados.forEach(n => { z1stats[k].jugadores[n] = { jugo: 'todo' }; }); });
  z1stats.fecha02_rival_b.jugadores.Feli = { jugo: 'entro' };
  // Zona actual (z2): una con motivos, otra vieja sin motivos, y las que faltan citar
  const z2cit = {
    fecha01_rival_d: mk(1, 'RIVAL D', ['Benja', 'Ciro', 'Feli', 'Santi'], '2026-08-15', { noCitados: { Mateo: 'lesion', Ramiro: 'rotacion' } }),
    fecha02_rival_e: mk(2, 'RIVAL E', ['Benja', 'Ciro', 'Mateo'], '2026-08-22'),
  };
  const z2stats = {};
  Object.keys(z2cit).forEach(k => { z2stats[k] = { jugadores: {} }; z2cit[k].citados.forEach(n => { z2stats[k].jugadores[n] = { jugo: 'todo' }; }); });
  // Asistencia de ESTA semana (para probar la pestaña Semana): los días de la semana que se piden (1 = lunes)
  const asisSemana = (dows, pres, aus) => {
    const h = new Date(); const lunes = new Date(h); lunes.setDate(h.getDate() - ((h.getDay() + 6) % 7));
    const out = {};
    dows.forEach(w => { const d = new Date(lunes); d.setDate(lunes.getDate() + (w - 1)); if (d > h) return; out[d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')] = { present: pres, absent: aus, reasons: {} }; });
    return out;
  };
  const att = {
    '2026-09-01': { present: ['Benja', 'Ciro', 'Feli'], absent: ['Mateo', 'Ramiro', 'Santi'], reasons: { Mateo: 'lesionado', Ramiro: 'sinaviso', Santi: 'personal' } },
    '2026-09-08': { present: ['Benja', 'Ciro', 'Feli', 'Santi'], absent: ['Mateo', 'Ramiro'], reasons: { Mateo: 'lesionado', Ramiro: 'sinaviso' } },
  };
  // Uso de la app de los últimos 12 días (tablero de uso)
  const hoyD = new Date();
  const dIso = k => { const d = new Date(hoyD); d.setDate(d.getDate() - k); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
  const ts = k => { const d = new Date(hoyD); d.setDate(d.getDate() - k); d.setHours(12, 0, 0, 0); return d.getTime(); };
  const usage = { clubA: {}, hernandez: {} };
  for (let k = 0; k < 12; k++) {
    if (k % 5 !== 3) { usage.clubA[dIso(k)] = usage.clubA[dIso(k)] || {}; usage.clubA[dIso(k)].PROFE = { n: 1 + (k % 2), s: 600 + k * 120, c: { cat16: 600 + k * 120 }, k: { cat16: 1 + (k % 2) }, u: ts(k), e: 'profe@x.com' }; }
    if (k < 4) { usage.clubA[dIso(k)] = usage.clubA[dIso(k)] || {}; usage.clubA[dIso(k)].PROFE2 = { n: 1, s: 1500, c: { cat16: 900, cat2014: 600 }, k: { cat16: 1, cat2014: 1 }, u: ts(k), e: 'p2@x.com' }; }
    if (k % 3 === 0) { usage.clubA[dIso(k)] = usage.clubA[dIso(k)] || {}; usage.clubA[dIso(k)].COORD = { n: 1, s: 400, c: { coord: 400 }, k: { coord: 1 }, u: ts(k), e: 'coord@x.com' }; }
    if (k === 9) { usage.hernandez[dIso(k)] = { PROFEH: { n: 2, s: 900, c: { cat16: 900 }, k: { cat16: 2 }, u: ts(k), e: 'h@x.com' } }; }
  }
  const zona = (nombre, orden) => ({ nombre, orden, ligaId: 'lisfi-zona-campeonato-2026' });
  const lisfi = { torneoActivo: 'lisfi-zona-campeonato-2026', ligaId: 'lisfi-zona-campeonato-2026', temporadas: { 'lisfi-zona-campeonato-2026': zona('Zona Campeonato 2026', 2) } };
  const clubLisfi = (nombre, ligaNombre, fixture) => ({
    nombre, cats: ['cat16'], config: Object.assign({ ligaNombre }, lisfi, { fixture }),
    cat16: { players: { p0: { nombre: 'Uno', activo: true } }, torneos: { 'lisfi-zona-campeonato-2026': { attendance: {}, citaciones: {}, stats: {} } } },
  });
  return {
    usage,
    users: {
      PROFE:    { role: 'profe', clubId: 'clubA', cat: 'cat16', email: 'profe@x.com' },
      PROFE2:   { role: 'profe', clubId: 'clubA', cats: ['cat16', 'cat2014'], email: 'p2@x.com' },     // dos categorías
      COORD:    { role: 'coordinator', clubId: 'clubA', email: 'coord@x.com' },
      PROFEH:   { role: 'profe', clubId: 'hernandez', cat: 'cat16', email: 'h@x.com' },
      COORDH:   { role: 'coordinator', clubId: 'hernandez', email: 'ch@x.com' },                        // club con fixture de liga
      PROFES:   { role: 'profe', clubId: 'sagrado-corazon', cat: 'cat16', email: 's@x.com' },
      PROFEB:   { role: 'profe', clubId: 'clubB', cat: 'cat16', email: 'b@x.com' },
      PROFEC:   { role: 'profe', clubId: 'clubC', cat: 'cat2021', email: 'c@x.com' },                  // categoría nueva
      COORDC:   { role: 'coordinator', clubId: 'clubC', email: 'cc@x.com' },
      SA:       { role: 'super-admin', email: 'sa@x.com' },
      BAJ1:     { email: 'baja@x.com', role: 'baja', bajaTs: 1 },                                        // usuario dado de baja
      BADROL:   { role: 'coordinador', clubId: 'clubA', email: 'bad@x.com' },                           // rol que la app no reconoce
      HUERFANO: { role: 'profe', clubId: 'noexiste', cat: 'cat16', email: 'h@nada.com' },               // club inexistente
      SINCAT:   { role: 'profe', clubId: 'clubA', email: 'sincat@x.com' },                              // profe sin categoría
    },
    // Fixture de la liga (para probar citaciones y pendientes en clubes que usan liga)
    ligas: { 'lisfi-zona-campeonato-2026': { fixture: { 1: { rival: 'X1' }, 2: { rival: 'TALLERES B.' }, 3: { rival: 'DEFENSA' }, 4: { rival: 'V.S CARLOS BCO.' }, 30: { rival: 'PROXIMO FC' } } } },
    clubs: {
      clubC: { nombre: 'Club C', cats: ['cat13', 'cat16', 'cat2021', 'cat13', 'cat16', 'cat2021'],
        config: { torneoActivo: 'zc', ligaNombre: 'CLUB C', temporadas: { zc: { nombre: 'Torneo C', orden: 1 } } },
        cat2021: { players: { p0: { nombre: 'Nene Uno', activo: true }, p1: { nombre: 'Nene Dos', activo: true } }, torneos: { zc: { attendance: {}, citaciones: {}, stats: {} } } } },
      hernandez: clubLisfi('HERNANDEZ', 'HERNANDEZ', { 1: { rival: 'X1', cond: 'L' }, 2: { rival: 'TALLERES B.', cond: 'V' }, 3: { rival: 'LIBRE', cond: '-' }, 4: { rival: 'V.S CARLOS BCO.', cond: 'L' }, 5: { rival: 'LA CURVA', cond: 'V' }, 6: { rival: 'SAGR. CORAZON', cond: 'L' } }),
      'sagrado-corazon': clubLisfi('SAGRADO CORAZON', 'SAGR. CORAZON', { 1: { rival: 'X1', cond: 'L' }, 2: { rival: 'X2', cond: 'V' }, 3: { rival: 'DEFENSA', cond: 'L' }, 4: { rival: 'ESTUD. LH', cond: 'V' }, 5: { rival: 'TALLERES B.', cond: 'L' }, 6: { rival: 'HERNANDEZ', cond: 'V' } }),
      clubB: { nombre: 'Club B', cats: ['cat16'], config: { torneoActivo: 'z9', ligaNombre: 'CLUB B', temporadas: { z9: { nombre: 'Torneo B 2026', orden: 1 } }, fixture: { 1: { rival: 'OTRO 1', cond: 'L' }, 2: { rival: 'OTRO 2', cond: 'V' } } },
        cat16: { players: { p0: { nombre: 'Bruno', activo: true }, p1: { nombre: 'Carlos', activo: true } }, torneos: { z9: { attendance: {}, citaciones: { fecha01_otro_1: { fecha: 1, rival: 'OTRO 1', citados: ['Bruno'], fecha_str: '2026-08-10', savedAt: '2026-08-10' } }, stats: {} } } } },
      clubA: {
        nombre: 'Club A', cats: ['cat16', 'cat2014'],
        config: {
          torneoActivo: 'z2', ligaNombre: 'CLUB A',
          temporadas: { z1: { nombre: 'Zona II B 2026', orden: 1 }, z2: { nombre: 'Zona Campeonato 2026', orden: 2 } },
          fixture: { 1: { rival: 'RIVAL D', cond: 'L' }, 2: { rival: 'RIVAL E', cond: 'V' }, 3: { rival: 'RIVAL F', cond: 'L' }, 4: { rival: 'RIVAL G', cond: 'V' } },
          // Entrenamiento suspendido (formato plano AAAA-MM-DD, como lo guarda el panel de coordinación)
          suspensionesEnt: { '2026-09-08': true },
        },
        // Los días van como TEXTO, como en producción. La 2014 entrena distinto del resto del club.
        diasEntrenamiento: ['2', '4'],
        diasPorCategoria: { cat2014: ['1', '3', '5'] },
        cat2014: { players: { q0: { nombre: 'Otro Uno', activo: true }, q1: { nombre: 'Otro Dos', activo: true } }, torneos: { z2: { attendance: asisSemana([1, 3], ['Otro Uno'], ['Otro Dos']), citaciones: {}, stats: {} } } },
        cat16: { players, torneos: { z1: { attendance: {}, citaciones: z1cit, stats: z1stats }, z2: { attendance: Object.assign({}, att, asisSemana([2, 4], ['Benja', 'Ciro'], ['Mateo'])), citaciones: z2cit, stats: z2stats } } },
      },
    },
  };
}

/* Con ?big=1: volumen parecido al real (20 jugadores con apellidos largos, ~110 entrenamientos,
   2 zonas de 22 citaciones con estadísticas). Sirve para medir rendimiento y anchos de pantalla. */
function agrandar(d) {
  const NL = ['Burruchaga', 'Aurichio', 'Carmelo', 'Dante', 'Cantaleano Miqueas', 'Baraglia Felipe', 'Gulino Mendieta Lisandro', 'Coronel Salvador', 'Ana', 'Sol'];
  const N = Array.from({ length: 20 }, (_, i) => NL[i % NL.length] + (i >= NL.length ? ' ' + i : ''));
  const pl = {}; N.forEach((n, i) => { pl['p' + i] = { nombre: n, activo: true }; });
  const c16 = d.clubs.clubA.cat16; c16.players = pl;
  const att = {}; const base = new Date('2026-03-01');
  for (let i = 0; i < 110; i++) {
    const dt = new Date(base.getTime() + i * 86400000 * 1.5), f = dt.toISOString().slice(0, 10);
    const pres = N.filter((_, k) => (k + i) % 4 !== 0);
    att[f] = { present: pres, absent: N.filter(n => !pres.includes(n)), reasons: {} };
  }
  const mkZ = (pref, y) => {
    const cit = {}, st = {};
    for (let f = 1; f <= 22; f++) {
      const k = 'fecha' + String(f).padStart(2, '0') + '_rival_' + f, cs = N.filter((_, i) => (i + f) % 3 !== 0);
      cit[k] = { fecha: f, rival: 'RIVAL ' + f, condicion: 'L', citados: cs, fecha_str: y + '-' + String(1 + (f % 9)).padStart(2, '0') + '-' + String(1 + f).padStart(2, '0'), savedAt: y + '-05-01', noCitados: {} };
      st[k] = { enContra: 1, jugadores: Object.fromEntries(cs.map(n => [n, { goles: f % 2, jugo: 'todo' }])) };
    }
    return { attendance: pref === 'z2' ? att : {}, citaciones: cit, stats: st };
  };
  c16.torneos = { z1: mkZ('z1', '2026'), z2: mkZ('z2', '2026') };
  return d;
}

http.createServer((q, r) => {
  const u = new URL(q.url, 'http://x');
  const p = u.pathname === '/' ? '/index.html' : u.pathname;
  try {
    if (p === '/seed.json') {
      r.setHeader('content-type', types['.json']);
      return r.end(JSON.stringify(u.searchParams.get('big') ? agrandar(seed()) : seed()));
    }
    const f = path.resolve(ROOT, '.' + p);
    if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.statusCode = 404; return r.end('no encontrado'); }
    let b = fs.readFileSync(f);
    if (p === '/index.html') {
      let h = b.toString('utf8');
      // Firebase de verdad → Firebase simulado
      h = h.replace(/"https:\/\/www\.gstatic\.com\/firebasejs\/[^"]+"/g, '"/tools/harness/fb-stub.js"');
      // Con ?smoke=1 se corre además el chequeo automático (smoke.js)
      if (u.searchParams.get('smoke')) h = h.replace('</body>', '<script src="/tools/harness/smoke.js"></script></body>');
      b = Buffer.from(h);
    }
    r.setHeader('content-type', types[path.extname(f)] || 'application/octet-stream');
    r.end(b);
  } catch (e) { r.statusCode = 500; r.end(String(e)); }
}).listen(PORT, () => console.log('Arnés de pruebas en http://localhost:' + PORT + '/?as=PROFE   (ver tools/harness/README.md)'));

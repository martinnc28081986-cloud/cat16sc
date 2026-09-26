# Arnés de pruebas de MI PLANTEL

Corre la app **real** (`index.html`) contra un Firebase **simulado en memoria**, con datos de ejemplo de
varios clubes de formas distintas. No usa credenciales ni toca datos reales. Sirve para comprobar que un
cambio anda igual en todos los clubes antes de publicarlo.

```
node tools/harness/server.js          # abre http://localhost:8125
```

Se necesita solo Node. Con `PORT=9000 node tools/harness/server.js` cambia el puerto.

## Entrar como cada usuario

`?as=<usuario>` entra directo, sin login:

| Usuario | Qué es | Para qué sirve |
|---|---|---|
| `PROFE` | profe de Club A, categoría 2016 | flujo normal del profe (citaciones, plantel, pos partido…) |
| `PROFE2` | profe de Club A con dos categorías | selector de categoría y cambio entre categorías |
| `COORD` | coordinador de Club A | panel de coordinación |
| `PROFEH` / `PROFES` | profe de Hernández / de Sagrado Corazón | clubes de la liga LISFI |
| `PROFEB` | profe de Club B | club chico, una categoría |
| `PROFEC` / `COORDC` | profe / coordinador de **Club C** | club **nuevo**: sin fixture, categoría 2021 y lista de categorías repetida |
| `SA` | super admin | panel de super admin (clubes, usuarios, uso, salud) |
| `BAJ1` | usuario dado de baja | tiene que quedar sin acceso |
| `BADROL`, `HUERFANO`, `SINCAT` | usuarios con datos mal armados **a propósito** | que "Salud de clubes" los marque |

Parámetros útiles: `&big=1` (volumen parecido al real, con apellidos largos), `&lat=200` (200 ms de latencia
de red simulada), `&smoke=1` (corre el chequeo automático).

## Chequeo automático (smoke)

```
http://localhost:8125/?as=PROFE&smoke=1
```

Recorre todas las pantallas de ese usuario y junta errores. El resultado queda en `window.__smoke` y en el
título de la pestaña (`SMOKE OK profe` / `SMOKE FALLA profe`). **Antes de publicar un cambio, correrlo con
`PROFE`, `PROFE2`, `COORD`, `COORDC`, `PROFEC`, `PROFEH` y `SA`** (y con `&big=1` para nombres largos).

## Qué se puede medir

- `window.__log`: lecturas a Firebase (para ver cuántas dispara una acción).
- `window.__writes`: escrituras.
- `window.__fbdb`: el contenido de la base simulada (para comprobar qué se guardó).
- `window.__listeners()`: listeners activos (para detectar acumulación al cambiar de categoría).

## Límites

Las **reglas de seguridad** de la base y el **login real** no se prueban acá (el simulado no las aplica): las
reglas se verifican aparte con el simulador de reglas y al publicarlas. Tampoco prueba un teléfono real.

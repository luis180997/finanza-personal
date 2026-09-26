"""Respaldos: siempre sobre carpetas temporales, nunca sobre data/."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import create_engine

from app.plataforma import respaldo

AHORA = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)     # domingo


@pytest.fixture(autouse=True)
def _sin_intentos_previos(monkeypatch):
    """El resultado del ultimo intento es de todo el proceso: que un test no herede
    el fallo provocado por otro."""
    monkeypatch.setattr(respaldo, "_ultimo_intento", None)


@pytest.fixture()
def base(tmp_path: Path) -> Path:
    ruta = tmp_path / "finanzas.db"
    con = sqlite3.connect(ruta)
    con.execute('create table "transaction" (id integer primary key, amount_cents integer)')
    con.executemany('insert into "transaction" (amount_cents) values (?)', [(i,) for i in range(500)])
    con.commit()
    con.close()
    return ruta


def _url(ruta: Path) -> str:
    return f"sqlite:///{ruta.as_posix()}"


def _nombre(momento: datetime) -> str:
    return f"finanzas_{momento:%Y%m%dT%H%M%SZ}.db"


def _vaciar(base: Path, quedan: int) -> None:
    con = sqlite3.connect(base)
    con.execute('delete from "transaction" where id > ?', (quedan,))
    con.commit()
    con.close()


def test_la_copia_es_una_base_integra_con_los_mismos_datos(base, tmp_path):
    carpeta = tmp_path / "respaldos"
    nuevo = respaldo.respaldar(_url(base), carpeta, conservar=0, forzar=True, ahora=AHORA)

    assert nuevo is not None
    assert nuevo.ruta.name == "finanzas_20260913T120000Z.db"
    assert nuevo.movimientos == 500
    con = sqlite3.connect(nuevo.ruta)
    assert con.execute('select count(*) from "transaction"').fetchone()[0] == 500
    con.close()
    # No quedan temporales a medio escribir
    assert [p.name for p in carpeta.iterdir()] == [nuevo.ruta.name]


def test_solo_respalda_cuando_pasaron_los_dias(base, tmp_path):
    carpeta = tmp_path / "respaldos"
    url = _url(base)
    assert respaldo.respaldar(url, carpeta, 0, cada_dias=7, ahora=AHORA)          # no habia ninguno
    assert respaldo.respaldar(url, carpeta, 0, cada_dias=7,
                              ahora=AHORA + timedelta(days=6, hours=23)) is None
    # Aunque la app estuviera apagada justo el dia 7, la copia sale al volver
    assert respaldo.respaldar(url, carpeta, 0, cada_dias=7, ahora=AHORA + timedelta(days=15))
    assert len(respaldo.listar(carpeta)) == 2


def test_cero_dias_desactiva_los_respaldos_automaticos(base, tmp_path):
    carpeta = tmp_path / "respaldos"
    assert respaldo.respaldar(_url(base), carpeta, 0, cada_dias=0, ahora=AHORA) is None
    assert not carpeta.exists()


def test_una_tarde_de_copias_seguidas_no_borra_las_de_otros_dias(base, tmp_path):
    """Con "las 8 ultimas", ocho respaldos manuales seguidos se llevaban el historial."""
    carpeta = tmp_path / "respaldos"
    carpeta.mkdir()
    ajeno = carpeta / "mi_copia_manual.db"
    ajeno.write_bytes(b"no es mio")
    url = _url(base)

    semana_pasada, ayer = AHORA - timedelta(days=7), AHORA - timedelta(days=1)
    respaldo.respaldar(url, carpeta, 3, forzar=True, ahora=semana_pasada)
    respaldo.respaldar(url, carpeta, 3, forzar=True, ahora=ayer)
    for minuto in range(10):
        respaldo.respaldar(url, carpeta, 3, forzar=True, ahora=AHORA + timedelta(minutes=minuto))

    assert [r.ruta.name for r in respaldo.listar(carpeta)] == [
        _nombre(AHORA + timedelta(minutes=9)),      # las 3 mas recientes
        _nombre(AHORA + timedelta(minutes=8)),
        _nombre(AHORA + timedelta(minutes=7)),
        _nombre(ayer),                              # la ultima de cada dia
        _nombre(semana_pasada),                     # y de la semana anterior
    ]
    assert ajeno.exists()


def test_con_el_tiempo_queda_una_por_dia_semana_y_mes():
    diarias = [respaldo.Respaldo(Path(f"copia{i}"), AHORA - timedelta(days=i), 0)
               for i in range(400)]
    quedan = respaldo._a_conservar(diarias, conservar=3)
    edades = sorted((AHORA - r.fecha).days for r in diarias if r.ruta in quedan)

    assert edades[:7] == list(range(7))             # la ultima semana, dia a dia
    assert 7 * 7 <= edades[-5] <= 12 * 31           # semanas y meses hacia atras...
    assert edades[-1] >= 300                        # ...hasta casi un ano
    assert len(quedan) <= 3 + 7 + 8 + 12


def test_una_copia_con_mas_movimientos_que_la_ultima_no_se_poda_nunca(base, tmp_path):
    """Una base vaciada por error se copia "sana". La copia buena tiene que sobrevivir
    a todas las que vengan despues, por muchas que sean."""
    carpeta = tmp_path / "respaldos"
    url = _url(base)
    buena = respaldo.respaldar(url, carpeta, 1, forzar=True, ahora=AHORA - timedelta(days=420))
    _vaciar(base, quedan=10)
    # Trece meses de copias de la base vaciada: la buena ya no la guarda ningun tramo
    for mes in range(12, -1, -1):
        respaldo.respaldar(url, carpeta, 1, forzar=True, ahora=AHORA - timedelta(days=30 * mes))

    nombres = {r.ruta.name for r in respaldo.listar(carpeta)}
    assert buena.ruta.name in nombres
    # Una copia igual de vieja pero sin perdida si se poda
    assert _nombre(AHORA - timedelta(days=360)) not in nombres


def test_el_estado_avisa_si_la_base_perdio_movimientos(base, tmp_path):
    carpeta = tmp_path / "respaldos"
    url = _url(base)
    respaldo.respaldar(url, carpeta, 0, forzar=True, ahora=AHORA)
    assert respaldo.estado(url, carpeta, 7, 8, ahora=AHORA)["alertas"] == []

    _vaciar(base, quedan=10)
    estado = respaldo.estado(url, carpeta, 7, 8, ahora=AHORA)
    assert estado["movimientos_en_uso"] == 10
    assert estado["ultimo"]["movimientos"] == 500
    assert any("La base tiene 10 movimientos" in a for a in estado["alertas"])

    respaldo.respaldar(url, carpeta, 0, forzar=True, ahora=AHORA + timedelta(hours=1))
    estado = respaldo.estado(url, carpeta, 7, 8, ahora=AHORA + timedelta(hours=1))
    assert any("antes habia 500" in a for a in estado["alertas"])
    assert estado["perdida_sin_aceptar"] is True


def test_un_borrado_a_proposito_se_puede_dar_por_bueno(base, tmp_path):
    """Sin esto, el aviso seguia hasta la siguiente copia (hasta 7 dias)."""
    carpeta = tmp_path / "respaldos"
    url = _url(base)
    respaldo.respaldar(url, carpeta, 0, forzar=True, ahora=AHORA)
    _vaciar(base, quedan=100)
    estado = respaldo.estado(url, carpeta, 7, 8, ahora=AHORA)
    assert estado["perdida_sin_aceptar"] and estado["alertas"]

    respaldo.aceptar_perdida(url, carpeta, ahora=AHORA + timedelta(minutes=5))
    estado = respaldo.estado(url, carpeta, 7, 8, ahora=AHORA + timedelta(minutes=5))
    assert estado["alertas"] == [] and not estado["perdida_sin_aceptar"]

    # La copia siguiente tampoco avisa de lo que ya diste por bueno...
    respaldo.respaldar(url, carpeta, 0, forzar=True, ahora=AHORA + timedelta(hours=1))
    assert respaldo.estado(url, carpeta, 7, 8, ahora=AHORA + timedelta(hours=1))["alertas"] == []
    # ...pero un borrado nuevo si
    _vaciar(base, quedan=50)
    assert respaldo.estado(url, carpeta, 7, 8, ahora=AHORA + timedelta(hours=1))["perdida_sin_aceptar"]
    # Y la copia con los 500 movimientos sigue ahi
    assert [r.movimientos for r in respaldo.listar(carpeta)] == [100, 500]


def test_una_copia_vencida_se_avisa(base, tmp_path):
    carpeta = tmp_path / "respaldos"
    respaldo.respaldar(_url(base), carpeta, 0, forzar=True, ahora=AHORA)
    alertas = respaldo.estado(_url(base), carpeta, 7, 8, ahora=AHORA + timedelta(days=20))["alertas"]
    assert any("hace 20 dias" in a for a in alertas)


def test_un_respaldo_del_futuro_no_bloquea_las_copias(base, tmp_path):
    carpeta = tmp_path / "respaldos"
    respaldo.respaldar(_url(base), carpeta, 0, forzar=True, ahora=AHORA + timedelta(days=30))
    assert respaldo.toca_respaldo(carpeta, 7, ahora=AHORA)


def test_sin_base_en_archivo_no_hay_respaldo_y_el_fallo_queda_a_la_vista(tmp_path):
    with pytest.raises(ValueError):
        respaldo.respaldar("postgresql://x/y", tmp_path, 0, forzar=True)
    url = _url(tmp_path / "no_existe.db")
    with pytest.raises(FileNotFoundError):
        respaldo.respaldar(url, tmp_path / "r", 0, forzar=True)

    estado = respaldo.estado(url, tmp_path / "r", 7, 8)
    assert estado["ultimo_intento"]["ok"] is False
    assert any("fallo" in a for a in estado["alertas"])


def test_al_arrancar_se_copia_la_base_antes_de_tocar_el_esquema(tmp_path, monkeypatch):
    """La copia "previa a migrar" se hacia despues de init_db: ya sin la tabla
    retirada y con las columnas nuevas."""
    import app.plataforma.db as app_db
    from app.plataforma import arranque
    from app.plataforma.config import settings

    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.execute('create table "transaction" (id integer primary key, amount_cents integer)')
    con.execute('insert into "transaction" (amount_cents) values (100)')
    con.execute("create table excel_staging (id integer primary key)")
    con.commit()
    con.close()

    motor = create_engine(_url(ruta))
    monkeypatch.setattr(app_db, "engine", motor)
    monkeypatch.setattr(settings, "database_url", _url(ruta))
    monkeypatch.setattr(settings, "respaldo_dir", str(tmp_path / "copias"))
    try:
        pendientes = app_db.cambios_pendientes()
        assert "columna transaction.locked_by_user" in pendientes
        assert "tabla retirada excel_staging" in pendientes

        arranque._respaldo_previo_a_cambios()
    finally:
        motor.dispose()

    (copia,) = respaldo.listar(tmp_path / "copias")
    con = sqlite3.connect(copia.ruta)
    assert con.execute("select name from sqlite_master where name = 'excel_staging'").fetchone()
    con.close()

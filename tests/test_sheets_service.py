import pandas as pd
from sqlalchemy import delete

from oraculoicms_app.models.matrix import Source, STRegra
from oraculoicms_app.services.sheets_service import (
    init_sheets,
    get_matrices,
    reload_matrices,
)


def _make_source(db_session, **kwargs):
    src = Source(
        nome=kwargs.get("nome", "Fonte"),
        ativo=kwargs.get("ativo", True),
        uf=kwargs.get("uf"),
        url=kwargs.get("url"),
        tipo=kwargs.get("tipo"),
        parser=kwargs.get("parser"),
        prioridade=kwargs.get("prioridade"),
    )
    db_session.add(src)
    return src


def test_init_sheets_populates_matrices(app, db_session):
    with app.app_context():
        _make_source(db_session, nome="Fonte X", uf="AM", tipo="csv")
        db_session.add(STRegra(ncm="123", ativo=True, st_aplica=True))
        db_session.commit()

        init_sheets(app)
        matrices = get_matrices()

        assert "sources" in matrices
        df_sources = matrices["sources"]
        assert isinstance(df_sources, pd.DataFrame)
        assert df_sources.loc[0, "NOME"] == "Fonte X"

        df_st = matrices["st_regras"]
        assert not df_st.empty
        assert df_st.loc[0, "NCM"] == "123"


def test_reload_matrices_reads_latest_data(app, db_session):
    with app.app_context():
        db_session.execute(delete(Source))
        db_session.commit()

        init_sheets(app)
        matrices = get_matrices()
        assert matrices["sources"].empty

        _make_source(db_session, nome="Nova Fonte", ativo=False)
        db_session.commit()

        updated = reload_matrices()
        df_sources = updated["sources"]
        assert len(df_sources.index) == 1
        assert df_sources.loc[0, "NOME"] == "Nova Fonte"
        assert df_sources.loc[0, "ATIVO"] == 0

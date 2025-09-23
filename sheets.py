import os
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from typing import Dict
from config import Config

# Escopos com leitura+escrita no Sheets
auth_scopes = [
    "https://www.googleapis.com/auth/spreadsheets",      # read/write
    "https://www.googleapis.com/auth/drive.readonly",
]

class SheetMisconfig(Exception):
    pass

class SheetClient:
    def __init__(self):
        sa_path = Config.GOOGLE_SERVICE_ACCOUNT_JSON
        if not sa_path or not os.path.exists(sa_path):
            raise SheetMisconfig(
                f"Credencial Service Account não encontrada: {sa_path!r}. "
                "Confira GOOGLE_SERVICE_ACCOUNT_JSON no .env e o caminho do arquivo."
            )
        try:
            creds = Credentials.from_service_account_file(sa_path, scopes=auth_scopes)
        except Exception as e:
            raise SheetMisconfig(f"Falha ao carregar credencial Service Account: {e}") from e

        self.service_email = getattr(creds, "service_account_email", "<desconhecido>")
        self.gc = gspread.authorize(creds)

        ssid = Config.SPREADSHEET_ID
        if not ssid or ssid.strip() == "":
            raise SheetMisconfig(
                "SPREADSHEET_ID vazio. Use SOMENTE o ID (trecho entre /d/ e /edit)."
            )
        try:
            self.sh = self.gc.open_by_key(ssid)
        except gspread.SpreadsheetNotFound as e:
            raise SheetMisconfig("Planilha NÃO encontrada. Verifique se o ID está correto.") from e
        except PermissionError as e:
            raise SheetMisconfig(
                "PERMISSION DENIED ao abrir a planilha.\n"
                f"• Compartilhe com: {self.service_email}\n"
                "• Permissão de Leitor/Editor.\n"
                "• Habilite Google Sheets API e Drive API."
            ) from e
        except Exception as e:
            raise SheetMisconfig(f"Falha inesperada ao abrir a planilha: {e}") from e

    # ---------- utilidades ----------
    def _has_ws(self, name: str) -> bool:
        try:
            self.sh.worksheet(name)
            return True
        except Exception:
            return False

    def df(self, worksheet_name: str) -> pd.DataFrame:
        ws = self.sh.worksheet(worksheet_name)
        rows = ws.get_all_records()
        return pd.DataFrame(rows)

    def write_df(self, worksheet_name: str, df: pd.DataFrame):
        """Sobrescreve completamente a aba informada."""
        if not self._has_ws(worksheet_name):
            self.sh.add_worksheet(title=worksheet_name, rows=1, cols=1)
        ws = self.sh.worksheet(worksheet_name)
        ws.clear()
        if df is None or df.empty:
            ws.update("A1", [["VAZIO"]])
            return
        df = df.fillna("")
        ws.update([df.columns.tolist()] + df.astype(str).values.tolist())

    def append_row(self, worksheet_name: str, row: list):
        if not self._has_ws(worksheet_name):
            self.sh.add_worksheet(title=worksheet_name, rows=1, cols=1)
        ws = self.sh.worksheet(worksheet_name)
        ws.append_row(row)

    # ---------- carga principal ----------
    def matrices(self) -> Dict[str, pd.DataFrame]:
        tabs = [
            "aliquotas",
            "mva",
            "multiplicadores",
            "creditos_presumidos",
            "excecoes",
            "config",
            "st_regras",
            "sources",
            "sources_log",
        ]
        out: Dict[str, pd.DataFrame] = {}
        for t in tabs:
            try:
                out[t] = self.df(t) if self._has_ws(t) else pd.DataFrame()
            except Exception:
                out[t] = pd.DataFrame()
        return out

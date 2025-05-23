import os
import asyncio
from datetime import datetime
from typing import List, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config.config import settings


class GoogleSheetsService:
    def __init__(self):
        if not settings.google_sheets_enabled:
            raise Exception("Google Sheets интеграция отключена")
        
        if not settings.google_sheets_credentials_file or not os.path.exists(settings.google_sheets_credentials_file):
            raise Exception("Файл с учетными данными Google не найден")
        
        if not settings.spreadsheet_id:
            raise Exception("ID таблицы Google Sheets не указан")
        
        # Инициализация сервиса
        self.creds = service_account.Credentials.from_service_account_file(
            settings.google_sheets_credentials_file,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        
        self.service = build('sheets', 'v4', credentials=self.creds)
        self.spreadsheet_id = settings.spreadsheet_id
    
    async def export_statistics(self, data: List[List[Any]], sheet_name: str) -> str:
        """Экспорт статистики в Google Sheets"""
        try:
            # Выполняем в отдельном потоке, так как googleapiclient синхронная
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._export_sync,
                data,
                sheet_name
            )
            return result
        except Exception as e:
            raise Exception(f"Ошибка при экспорте в Google Sheets: {str(e)}")
    
    def _export_sync(self, data: List[List[Any]], sheet_name: str) -> str:
        """Синхронный метод экспорта"""
        try:
            # Получаем список листов
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            sheets = spreadsheet.get('sheets', [])
            sheet_exists = any(sheet['properties']['title'] == sheet_name for sheet in sheets)
            
            if not sheet_exists:
                # Создаем новый лист
                request_body = {
                    'requests': [{
                        'addSheet': {
                            'properties': {
                                'title': sheet_name,
                                'gridProperties': {
                                    'rowCount': len(data) + 10,
                                    'columnCount': len(data[0]) if data else 10
                                }
                            }
                        }
                    }]
                }
                
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body=request_body
                ).execute()
            else:
                # Очищаем существующий лист
                self.service.spreadsheets().values().clear(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet_name}!A1:Z1000"
                ).execute()
            
            # Записываем данные
            body = {
                'values': data
            }
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_name}!A1",
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            # Форматируем заголовок
            self._format_header(sheet_name)
            
            # Возвращаем ссылку на таблицу
            return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit#gid={self._get_sheet_id(sheet_name)}"
            
        except HttpError as error:
            raise Exception(f"HTTP ошибка: {error}")
    
    def _format_header(self, sheet_name: str):
        """Форматирование заголовка таблицы"""
        try:
            sheet_id = self._get_sheet_id(sheet_name)
            
            requests = [{
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': 0,
                        'endRowIndex': 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': {
                                'red': 0.2,
                                'green': 0.4,
                                'blue': 0.8
                            },
                            'textFormat': {
                                'foregroundColor': {
                                    'red': 1.0,
                                    'green': 1.0,
                                    'blue': 1.0
                                },
                                'fontSize': 12,
                                'bold': True
                            }
                        }
                    },
                    'fields': 'userEnteredFormat(backgroundColor,textFormat)'
                }
            }, {
                'autoResizeDimensions': {
                    'dimensions': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': 0,
                        'endIndex': 10
                    }
                }
            }]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            # Не критичная ошибка, просто логируем
            print(f"Ошибка форматирования: {e}")
    
    def _get_sheet_id(self, sheet_name: str) -> int:
        """Получение ID листа по имени"""
        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id
        ).execute()
        
        for sheet in spreadsheet.get('sheets', []):
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']
        
        return 0
    
    async def create_daily_report(self, data: dict):
        """Создание ежедневного отчета"""
        report_data = [
            ["Ежедневный отчет", datetime.now().strftime("%Y-%m-%d %H:%M")],
            [],
            ["Показатель", "Значение"],
            ["Всего сообщений", data.get("total_messages", 0)],
            ["Отвечено", data.get("responded_messages", 0)],
            ["Пропущено", data.get("missed_messages", 0)],
            ["Среднее время ответа (мин)", data.get("avg_response_time", 0)],
            ["Эффективность (%)", data.get("efficiency", 0)]
        ]
        
        sheet_name = f"Отчет_{datetime.now().strftime('%Y_%m_%d')}"
        return await self.export_statistics(report_data, sheet_name) 
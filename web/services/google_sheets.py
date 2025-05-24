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
        print(f"🔍 [SHEETS DEBUG] Инициализация GoogleSheetsService")
        print(f"🔍 [SHEETS DEBUG] settings.google_sheets_enabled = {settings.google_sheets_enabled}")
        print(f"🔍 [SHEETS DEBUG] Тип: {type(settings.google_sheets_enabled)}")
        print(f"🔍 [SHEETS DEBUG] settings.google_sheets_credentials_file = {settings.google_sheets_credentials_file}")
        print(f"🔍 [SHEETS DEBUG] settings.spreadsheet_id = {settings.spreadsheet_id}")
        
        if not settings.google_sheets_enabled:
            print(f"❌ [SHEETS DEBUG] Google Sheets интеграция отключена! Значение: {settings.google_sheets_enabled}")
            raise Exception("Google Sheets интеграция отключена")
        
        if not settings.google_sheets_credentials_file or not os.path.exists(settings.google_sheets_credentials_file):
            print(f"❌ [SHEETS DEBUG] Файл credentials не найден: {settings.google_sheets_credentials_file}")
            raise Exception("Файл с учетными данными Google не найден")
        
        if not settings.spreadsheet_id:
            print(f"❌ [SHEETS DEBUG] ID таблицы не указан: {settings.spreadsheet_id}")
            raise Exception("ID таблицы Google Sheets не указан")
        
        print(f"✅ [SHEETS DEBUG] Все проверки пройдены, инициализируем API...")
        
        # Инициализация сервиса
        self.creds = service_account.Credentials.from_service_account_file(
            settings.google_sheets_credentials_file,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        
        self.service = build('sheets', 'v4', credentials=self.creds)
        self.spreadsheet_id = settings.spreadsheet_id
        
        print(f"✅ [SHEETS DEBUG] GoogleSheetsService успешно инициализирован")
    
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
    
    async def export_employees_statistics(self, employees_stats: List, period: str = "today") -> str:
        """Экспорт статистики сотрудников"""
        try:
            # Формируем данные для экспорта
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet_name = f"Статистика_сотрудников_{period}"
            
            # Заголовки
            headers = [
                "ID сотрудника",
                "ФИО",
                "Telegram ID", 
                "Username",
                "Статус",
                "Админ",
                "Всего сообщений",
                "Отвечено",
                "Пропущено",
                "Среднее время ответа (мин)",
                "Превышений 15 мин",
                "Превышений 30 мин", 
                "Превышений 60 мин",
                "Процент ответов (%)",
                "Эффективность (%)",
                "Период"
            ]
            
            # Данные
            data = [
                [f"Статистика сотрудников - {period.upper()}", "", "", "", "", "", "", "", "", "", "", "", "", "", "", f"Обновлено: {current_time}"],
                [],
                headers
            ]
            
            for emp in employees_stats:
                row = [
                    emp.employee_id,
                    emp.employee_name,
                    emp.telegram_id,
                    emp.telegram_username or "-",
                    "Активен" if emp.is_active else "Неактивен",
                    "Да" if emp.is_admin else "Нет",
                    emp.total_messages,
                    emp.responded_messages,
                    emp.missed_messages,
                    round(emp.avg_response_time or 0, 1),
                    emp.exceeded_15_min,
                    emp.exceeded_30_min,
                    emp.exceeded_60_min,
                    round(emp.response_rate, 1),
                    round(emp.efficiency_percent, 1),
                    f"{emp.period_start.strftime('%Y-%m-%d')} - {emp.period_end.strftime('%Y-%m-%d')}"
                ]
                data.append(row)
                
            # Добавляем итоговую строку
            if employees_stats:
                data.append([])
                data.append([
                    "ИТОГО:", "",
                    "", "", "", "",
                    sum(emp.total_messages for emp in employees_stats),
                    sum(emp.responded_messages for emp in employees_stats),
                    sum(emp.missed_messages for emp in employees_stats),
                    round(sum(emp.avg_response_time or 0 for emp in employees_stats) / len(employees_stats), 1),
                    sum(emp.exceeded_15_min for emp in employees_stats),
                    sum(emp.exceeded_30_min for emp in employees_stats),
                    sum(emp.exceeded_60_min for emp in employees_stats),
                    round(sum(emp.response_rate for emp in employees_stats) / len(employees_stats), 1),
                    round(sum(emp.efficiency_percent for emp in employees_stats) / len(employees_stats), 1),
                    ""
                ])
            
            return await self.export_statistics(data, sheet_name)
            
        except Exception as e:
            raise Exception(f"Ошибка при экспорте статистики сотрудников: {str(e)}")

    async def export_detailed_employee_report(self, employee_stats, messages: List = None) -> str:
        """Экспорт детального отчета по сотруднику"""
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet_name = f"Отчет_{employee_stats.employee_name}_{employee_stats.period_name}"
            
            # Общая информация
            data = [
                [f"Детальный отчет по сотруднику: {employee_stats.employee_name}", "", "", "", "", f"Обновлено: {current_time}"],
                [],
                ["Информация о сотруднике", ""],
                ["ФИО", employee_stats.employee_name],
                ["Telegram ID", employee_stats.telegram_id],
                ["Username", employee_stats.telegram_username or "-"],
                ["Статус", "Активен" if employee_stats.is_active else "Неактивен"],
                ["Роль", "Администратор" if employee_stats.is_admin else "Сотрудник"],
                [],
                ["Статистика за период", ""],
                ["Период", f"{employee_stats.period_start.strftime('%Y-%m-%d')} - {employee_stats.period_end.strftime('%Y-%m-%d')}"],
                ["Всего сообщений", employee_stats.total_messages],
                ["Отвечено", employee_stats.responded_messages],
                ["Пропущено", employee_stats.missed_messages],
                ["Среднее время ответа (мин)", round(employee_stats.avg_response_time or 0, 1)],
                ["Превышений 15 минут", employee_stats.exceeded_15_min],
                ["Превышений 30 минут", employee_stats.exceeded_30_min],
                ["Превышений 60 минут", employee_stats.exceeded_60_min],
                ["Процент ответов", f"{round(employee_stats.response_rate, 1)}%"],
                ["Эффективность", f"{round(employee_stats.efficiency_percent, 1)}%"],
                []
            ]
            
            # Если есть сообщения, добавляем их список
            if messages:
                data.extend([
                    ["Последние сообщения", "", "", "", ""],
                    ["Дата/время", "Тип", "Время ответа (мин)", "Отвечено", "Текст сообщения"]
                ])
                
                for msg in messages[:20]:  # Показываем последние 20 сообщений
                    data.append([
                        msg.received_at.strftime("%Y-%m-%d %H:%M:%S") if msg.received_at else "-",
                        msg.message_type or "-",
                        round(msg.response_time_minutes or 0, 1) if msg.response_time_minutes else "-",
                        "Да" if msg.responded_at else "Нет",
                        (msg.message_text or "")[:100] + "..." if msg.message_text and len(msg.message_text) > 100 else msg.message_text or "-"
                    ])
            
            return await self.export_statistics(data, sheet_name)
            
        except Exception as e:
            raise Exception(f"Ошибка при экспорте детального отчета: {str(e)}")
    
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
                                    'columnCount': len(data[0]) if data else 20
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
                # Форматируем строку с заголовками таблицы (3-я строка)
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': 2,
                        'endRowIndex': 3
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': {
                                'red': 0.9,
                                'green': 0.9,
                                'blue': 0.9
                            },
                            'textFormat': {
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
                        'endIndex': 20
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
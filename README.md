# CRMpro — Sistema de gestión comercial con IA

Flask + Ollama + SQLite. Login, registro y sugerencias de seguimiento con IA local.

## Instalación

```bash
pip install -r requirements.txt
```

Asegúrate de tener Ollama:
```bash
ollama serve        # en una terminal
ollama pull llama3  # una sola vez
```

## Ejecutar

```bash
python app.py
```

Abre: http://localhost:5000

## Páginas

| Ruta | Descripción |
|------|-------------|
| `/login` | Inicio de sesión |
| `/registro` | Registro + opción de datos demo |
| `/` | Dashboard con métricas |
| `/clientes` | Listado con filtros y búsqueda |
| `/cliente/<id>` | Ficha completa + IA |
| `/perfil` | Editar datos y contraseña |

## Cambiar modelo Ollama

En `app.py` línea 10:
```python
OLLAMA_MODEL = "llama3"  # o llama3.2, mistral, gemma2...
```

## Estructura

```
crm-comercial/
├── app.py
├── requirements.txt
├── crm.db              # se crea automáticamente
└── templates/
    ├── base.html
    ├── login.html
    ├── registro.html
    ├── index.html
    ├── clientes.html
    ├── cliente_detalle.html
    └── perfil.html
```

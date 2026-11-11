# run.py (Crear en la raíz de VEXA_LOCAL)
from waitress import serve

# Importamos la aplicación desde la carpeta VexaApp
# (Asegúrate de cambiar 'web_app' por 'app' si tu app principal está en app.py)
from VexaApp.web_app import app  

if __name__ == '__main__':
    print("=" * 50)
    print(" Servidor Waitress para VEXA_LOCAL iniciado")
    print(" Acceso local: http://127.0.0.1:8080")
    print(" Acceso remoto (Tailscale): http://<TU-IP-DE-TAILSCALE>:8080")
    print("=" * 50)
    
    # Servimos la app abierta para conexiones de Tailscale
    serve(app, host='0.0.0.0', port=8080)
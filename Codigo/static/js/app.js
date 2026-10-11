/* ==================== PIN TECLADO ==================== */
let currentPin = '';
let pinActive = true;
const circles = document.querySelectorAll('.pin-circle');

window.addEventListener('keydown', (e) => {
    if (!pinActive) return;

    if (e.key >= '0' && e.key <= '9' && currentPin.length < 4) {
        currentPin += e.key;
        actualizarVistaPin();
        if (currentPin.length === 4) validarPin();
    } else if (e.key === 'Backspace' && currentPin.length > 0) {
        currentPin = currentPin.slice(0, -1);
        actualizarVistaPin();
    }
});

function actualizarVistaPin() {
    document.getElementById('pinError').textContent = '';
    circles.forEach((circle, index) => {
        circle.classList.remove('error');
        if (index < currentPin.length) circle.classList.add('filled');
        else circle.classList.remove('filled');
    });
}

async function validarPin() {
    const res = await pywebview.api.validar_o_crear_pin(currentPin);
    if (res.ok) {
        pinActive = false;
        document.getElementById('pinOverlay').style.display = 'none';
        document.getElementById('statusText').textContent = "Sistema listo.";
        document.getElementById('questionInput').focus();
    } else {
        const pinCard = document.getElementById('pinCard');
        pinCard.classList.add('shake');
        document.getElementById('pinError').textContent = res.mensaje;
        circles.forEach(c => c.classList.add('error'));

        setTimeout(() => {
            pinCard.classList.remove('shake');
            currentPin = '';
            actualizarVistaPin();
        }, 500);
    }
}

/* ==================== DRAG & DROP GLOBAL Y DE ZONA ==================== */
const dropzone = document.getElementById('dropzone');

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    document.body.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
    }, false);
});

['dragenter', 'dragover'].forEach(name => {
    document.body.addEventListener(name, () => dropzone.classList.add('dragover'));
});

['dragleave', 'drop'].forEach(name => {
    document.body.addEventListener(name, () => dropzone.classList.remove('dragover'));
});

document.body.addEventListener('drop', async (e) => {
    const files = Array.from(e.dataTransfer.files).map(f => f.path).filter(Boolean);
    if (files.length > 0) {
        document.getElementById('statusText').textContent = "Procesando archivos...";
        const tiempoLimite = parseInt(document.getElementById('expirySelect').value, 10);
        const res = await pywebview.api.procesar_rutas(files, tiempoLimite);
        actualizarEstadoArchivos(res);
    }
});

async function seleccionarDocumentos() {
    document.getElementById('statusText').textContent = "Abriendo selector...";
    const tiempoLimite = parseInt(document.getElementById('expirySelect').value, 10);
    const res = await pywebview.api.seleccionar_documentos(tiempoLimite);
    actualizarEstadoArchivos(res);
}

function actualizarEstadoArchivos(res) {
    if (res.mensaje) document.getElementById('statusText').textContent = res.mensaje;
    renderizarListaArchivos(res.archivos || []);
}

function renderizarListaArchivos(archivos) {
    const fileList = document.getElementById('fileList');
    const emptyState = document.getElementById('fileListEmpty');

    // Recordar cuáles estaban marcados antes de redibujar
    const marcadosPrevios = new Set(
        Array.from(document.querySelectorAll('.file-checkbox:checked')).map(cb => cb.value)
    );

    fileList.innerHTML = '';

    if (!archivos.length) {
        emptyState.style.display = 'block';
        return;
    }
    emptyState.style.display = 'none';

    archivos.forEach(archivo => {
        const item = document.createElement('div');
        item.className = 'file-item' + (archivo.por_vencer ? ' file-item--warning' : '');

        const debeMarcarse = marcadosPrevios.size === 0 || marcadosPrevios.has(archivo.nombre);

        item.innerHTML = `
            <label>
                <input type="checkbox" class="file-checkbox" value="${archivo.nombre}" ${debeMarcarse ? 'checked' : ''}>
                <div class="file-item__info">
                    <span class="file-item__name">📄 ${archivo.nombre}</span>
                    <span class="file-item__expiry">⏳ ${archivo.tiempo_restante_texto}</span>
                </div>
            </label>
            <button class="file-item__remove" title="Quitar archivo" onclick="quitarArchivo('${archivo.nombre.replace(/'/g, "\\'")}')">✕</button>
        `;
        fileList.appendChild(item);
    });
}

async function quitarArchivo(nombre) {
    const res = await pywebview.api.eliminar_archivo(nombre);
    actualizarEstadoArchivos(res);
}

async function refrescarEstadoArchivos() {
    try {
        const res = await pywebview.api.estado_archivos();
        renderizarListaArchivos(res.archivos || []);
        if (res.expiraron) {
            document.getElementById('statusText').textContent = "Uno o más archivos vencieron y fueron retirados del contexto.";
        }
    } catch (e) {
        // pywebview aún no está listo, se ignora silenciosamente
    }
}

// Revisa expiraciones cada 60 segundos sin que el usuario tenga que hacer nada
setInterval(refrescarEstadoArchivos, 60000);

/* ==================== CHAT Y ENTER ==================== */
function renderMarkdown(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/^- (.*$)/gim, '• $1')
        .replace(/\n/g, '<br>');
}

document.getElementById('questionInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        enviarPregunta();
    }
});

async function enviarPregunta() {
    const input = document.getElementById('questionInput');
    const btn = document.getElementById('sendButton');
    const pregunta = input.value.trim();
    if (!pregunta) return;

    const seleccionados = Array.from(document.querySelectorAll('.file-checkbox:checked')).map(cb => cb.value);

    agregarMensaje(pregunta, 'user');
    input.value = '';
    input.disabled = true;
    btn.disabled = true;

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message assistant thinking';
    loadingDiv.id = 'loadingMsg';
    loadingDiv.innerHTML = `<span class="dot-flashing"></span> Consultando información en los documentos...`;
    document.getElementById('messages').appendChild(loadingDiv);
    document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;

    const respuesta = await pywebview.api.responder_pregunta(pregunta, seleccionados);

    const loader = document.getElementById('loadingMsg');
    if (loader) loader.remove();

    input.disabled = false;
    btn.disabled = false;
    input.focus();

    // responder_pregunta siempre devuelve {texto, fuentes}
    agregarMensaje(respuesta.texto, 'assistant', respuesta.fuentes || []);
}

function agregarMensaje(texto, tipo, fuentes = []) {
    const container = document.getElementById('messages');
    const msg = document.createElement('div');
    msg.className = `message ${tipo}`;
    msg.innerHTML = renderMarkdown(texto);

    if (fuentes.length > 0) {
        const fuentesDiv = document.createElement('div');
        fuentesDiv.className = 'message__sources';
        fuentesDiv.innerHTML = '📎 ' + fuentes.map(f => `<span class="source-chip">${f}</span>`).join('');
        msg.appendChild(fuentesDiv);
    }

    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

function nuevaConversacion() {
    const container = document.getElementById('messages');
    container.innerHTML = '<div class="message assistant">Hola. Soy VEXA. Carga tus documentos y escribe tu consulta.</div>';
    document.getElementById('questionInput').focus();
}

window.addEventListener('pywebviewready', async () => {
    const requierePin = await pywebview.api.requiere_pin();
    if (!requierePin) {
        document.getElementById('pinTitle').textContent = "CONFIGURAR PIN";
        document.getElementById('pinSub').textContent = "Cree un PIN de 4 dígitos con el teclado.";
    }
    // Si ya había archivos cargados de una sesión anterior (y siguen
    // vigentes dentro de las 2 horas), los mostramos de inmediato.
    await refrescarEstadoArchivos();
});

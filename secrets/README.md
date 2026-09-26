# secrets/

Aqui va **`credentials.json`**: el JSON de OAuth que descargas de Google Cloud Console
(tipo "Aplicacion web").

Se monta en el contenedor en **solo lectura**. El token que genera la autorizacion
(`token.json`) NO vive aqui: se guarda en el volumen de datos.

Esta carpeta esta excluida de git. Nunca subas su contenido a ningun sitio.

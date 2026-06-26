# scripts/_experimentos

Scripts de prueba **manuales** y de extremo a extremo (E2E). **No son tests
deterministas** y **no corren en CI**: requieren clave de API real, conexión a
internet y PDFs concretos del equipo del usuario.

- `test_corrector.py` — corre el pipeline completo del corrector en modo headless
  contra un PDF real usando la API de Claude. Verifica densidad de hallazgos,
  generación de entregables y distribución de anotaciones. Necesita
  `ANTHROPIC_API_KEY` y la ruta del PDF de prueba (editar las constantes al inicio).
- `run_prueba.py` — variante de ejecución manual del pipeline sobre un PDF.

Para los tests automáticos y reproducibles (sin red), ver `../../tests/`.

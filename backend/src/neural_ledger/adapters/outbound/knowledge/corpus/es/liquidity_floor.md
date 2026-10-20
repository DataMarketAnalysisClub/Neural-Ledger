---
{
  "id": "liquidity_floor",
  "lang": "es",
  "title": "Piso de liquidez",
  "aliases": ["saldo mínimo", "saldo mínimo de la cuenta", "minimum balance"],
  "tags": ["neural ledger", "flujo de caja"],
  "related": ["protected_surplus", "liquidity", "emergency_fund", "budget"],
  "sources": [
    {"title": "Neural Ledger decisions (ADR-037)", "url": "https://github.com/DataMarketAnalysisClub/Neural-Ledger/blob/main/docs/DECISIONS.md", "license": "project documentation"}
  ],
  "numbers": []
}
---
El piso de liquidez es el saldo mínimo que decides mantener siempre en tu cuenta. La plata por debajo de esa línea no se considera disponible para gastar, aunque el saldo se vea alto ese día.

En Neural Ledger, el copiloto puede proponerte un piso a partir de tu historial, pero el número solo rige cuando lo confirmas en la app. Puedes subirlo, bajarlo o dejar el actual; la decisión siempre es tuya.

El piso afecta tu excedente protegido. Como más plata tiene que quedarse en la cuenta, un piso más alto baja el excedente. Es una herramienta de planificación para el día a día, no un producto de ahorro ni una promesa, y es distinta del fondo de emergencia, que se reserva para gastos grandes e imprevistos.

Esto es información general, no una recomendación.

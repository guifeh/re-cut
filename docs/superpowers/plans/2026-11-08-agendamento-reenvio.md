# Agendamento e envio pela grade de cortes

## Comportamento

A grade oferece seleção de cortes e um menu de três pontos por vídeo. Cada corte pode ser enviado ao YouTube ou Telegram independentemente da aprovação na esteira. O YouTube aceita uma data futura com fuso explícito e agenda a publicação nos servidores da plataforma. A seleção múltipla usa data inicial e intervalo em minutos, com prévia da ordem. O padrão é 30 minutos.

O envio usa os metadados e a legenda já escolhida, preserva os estados das outras plataformas e registra o resultado em .publicacao. Reenvios confirmados guardam o estado anterior no histórico. Envios ativos são bloqueados e resultados incertos exigem confirmação. Agendamentos passados são recusados antes do upload. Cortes antigos e os oito agendamentos existentes continuam legíveis.

## Implementação

1. Em publicar.py, preparar envio por destino, validar datas e adicionar publishAt ao upload privado do YouTube. Cobrir seleção de destino, duplicação, falhas e datas em testes de regressão.
2. Em server.py, expor o envio individual usando o registro de threads existente. Testar a rota com HTTP falso e diretórios temporários.
3. Em frontend/src/api.ts e um componente da grade, implementar seleção, menu acessível, confirmação de reenvio e diálogo de agendamento com prévia dos horários.
4. Rodar pytest e build do frontend. Conferir o fluxo visual e reiniciar o servidor local após confirmar que não há uploads ou jobs ativos.

## Verificação

Os testes usam HTTP simulado. A validação da interface não publica vídeos reais.

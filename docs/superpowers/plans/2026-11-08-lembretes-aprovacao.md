# Lembretes de aprovação no Telegram

Cada JSON de corte pronto é um evento persistido pela renderização. Um worker no servidor consulta esses eventos a cada 30 segundos e identifica cortes há pelo menos dez minutos na aprovação. O listener do Telegram continua independente, recebendo respostas e links.

O worker agrupa os cortes vencidos do mesmo job em uma mensagem com títulos e instrução para abrir a aprovação no computador. O aviso é registrado em .publicacao por corte e bot/chat, junto aos demais estados já persistidos. Aprovação ou recusa pela lixeira remove a elegibilidade. Reiniciar o servidor mantém os avisos registrados.

Falha HTTP recusada pode ser tentada novamente após espera. Resultado de rede incerto fica registrado sem repetição automática, pois a mensagem pode ter chegado. O envio do lembrete não aprova nem publica o vídeo.

Implementar lembretes.py com seleção, consumo e worker, inicializar em server.py e cobrir prazo, aprovação, exclusão, agrupamento, reinício, concorrência e falhas com relógio e HTTP simulados.

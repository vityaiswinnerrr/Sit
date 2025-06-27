const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const { Rcon } = require('rcon-client');

const app = express();
app.use(bodyParser.json());

// 🔐 Введи свої дані
const MONO_TOKEN = 'uwXdXqxAZnNiE8sEafXhrol_Kkg3gmwGgoL8uax7td0w';
const JAR_ID = '3NFVTVCMp';
const RCON_HOST = 'QGtNBbQtt4';
const RCON_PORT = 25874; // або свій порт
const RCON_PASSWORD = 'QGtNBbQtt4';

let lastChecked = 0;

function getCommand(nick, product, type, quantity = 1) {
  product = product.toLowerCase();

  if (type === 'donate') {
    if (product === 'pan') return `give ${nick} minecraft:diamond 1`;
    if (product === 'lord') return `lp user ${nick} parent add lord`;
    if (product === 'sponsor') return `lp user ${nick} parent add sponsor`;
  }

  if (type === 'case') {
    if (product === 'донат-кейс') return `give ${nick} minecraft:ender_chest ${quantity}`;
    if (product === 'титул-кейс') return `give ${nick} minecraft:name_tag ${quantity}`;
  }

  if (type === 'currency') {
    if (product === '100 монет') return `eco give ${nick} 100`;
    if (product === '250 монет') return `eco give ${nick} 250`;
    if (product === '500 монет') return `eco give ${nick} 500`;
    if (product === '1000 монет') return `eco give ${nick} 1000`;
  }

  return null;
}

app.get('/check-payment', async (req, res) => {
  try {
    const response = await axios.get(`https://api.monobank.ua/personal/statement/jar/${JAR_ID}/${lastChecked}`, {
      headers: { 'X-Token': MONO_TOKEN }
    });

    const transactions = response.data;
    console.log(`Отримано транзакцій: ${transactions.length}`);

    for (const tx of transactions) {
      lastChecked = tx.time + 1;
      const comment = tx.comment;

      if (!comment) continue;

      const parts = comment.split('|').map(p => p.trim());
      if (parts.length < 2) continue;

      const nick = parts[0];
      const product = parts[1];
      const quantity = parts.length >= 3 ? parseInt(parts[2]) || 1 : 1;

      const type = product.toLowerCase().includes('кейс') ? 'case' : (product.toLowerCase().includes('монет') ? 'currency' : 'donate');

      const command = getCommand(nick, product, type, quantity);
      if (!command) continue;

      console.log(`Відправляємо команду RCON: ${command}`);

      try {
        const rcon = await Rcon.connect({
          host: RCON_HOST,
          port: RCON_PORT,
          password: RCON_PASSWORD
        });

        await rcon.send(command);
        await rcon.end();

        console.log('✅ Команда відправлена успішно');
        return res.json({ status: 'done', command });
      } catch (err) {
        console.error('❌ Помилка при відправці команди RCON:', err.message);
        return res.status(500).json({ status: 'error', error: err.message });
      }
    }

    res.json({ status: 'wait' });
  } catch (e) {
    console.error('❌ Помилка Monobank API:', e.message);
    res.status(500).json({ status: 'error', error: e.message });
  }
});

app.listen(3000, () => {
  console.log('🚀 Сервер запущено на http://localhost:3000');
});

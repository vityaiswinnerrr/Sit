const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const { Rcon } = require('rcon-client');

const app = express();
app.use(bodyParser.json());

// 🔐 Дані доступу
const MONO_TOKEN = 'uwXdXqxAZnNiE8sEafXhrol_Kkg3gmwGgoL8uax7td0w';
const JAR_ID = '3NFVTVCMp';
const RCON_HOST = '107.161.154.161';
const RCON_PORT = 25874;
const RCON_PASSWORD = 'QGtNBbQtt4';

let lastChecked = 0;

// 🔤 Функція нормалізації ніку (перша велика, інші малі)
function formatNick(name) {
  if (!name) return '';
  return name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
}

// 🎮 Генерація команди для видачі
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
    const coins = parseInt(product);
    if (!isNaN(coins)) return `eco give ${nick} ${coins}`;
  }

  return null;
}

app.get('/check-payment', async (req, res) => {
  try {
    const response = await axios.get(
      `https://api.monobank.ua/personal/statement/jar/${JAR_ID}/${lastChecked}`,
      { headers: { 'X-Token': MONO_TOKEN } }
    );

    const transactions = response.data;
    console.log(`🔍 Отримано ${transactions.length} транзакцій`);

    for (const tx of transactions) {
      lastChecked = tx.time + 1;
      const comment = tx.comment;
      console.log('\n📩 Коментар:', comment);

      if (!comment) continue;

      const parts = comment.split('|').map(p => p.trim());
      if (parts.length < 2) continue;

      const nick = formatNick(parts[0]);
      const product = parts[1];
      const quantity = parts.length >= 3 ? parseInt(parts[2]) || 1 : 1;

      // Тип товару
      let type = 'donate';
      if (product.toLowerCase().includes('кейс')) type = 'case';
      else if (product.toLowerCase().includes('монет')) {
        type = 'currency';
        const match = product.match(/\d+/);
        if (match) product = match[0]; // Витягуємо 100/250/500/1000
      }

      const command = getCommand(nick, product, type, quantity);
      if (!command) {
        console.log(`⚠️ Команда не знайдена для "${product}"`);
        continue;
      }

      console.log(`📤 Відправка RCON: ${command}`);

      try {
        const rcon = await Rcon.connect({
          host: RCON_HOST,
          port: RCON_PORT,
          password: RCON_PASSWORD
        });

        await rcon.send(command);
        await rcon.end();

        console.log('✅ Команда надіслана!');
        return res.json({ status: 'done', command });
      } catch (err) {
        console.error('❌ Помилка RCON:', err.message);
        return res.status(500).json({ status: 'error', error: err.message });
      }
    }

    console.log('⏳ Нових оплат немає');
    res.json({ status: 'wait' });
  } catch (e) {
    console.error('❌ Помилка Monobank API:', e.message);
    res.status(500).json({ status: 'error', error: e.message });
  }
});

app.listen(3000, () => {
  console.log('🚀 Сервер працює на http://localhost:3000');
});

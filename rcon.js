const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const { Rcon } = require('rcon-client');

const app = express();
app.use(bodyParser.json());

// 🔐 Введи свої дані:
const MONO_TOKEN = 'uwXdXqxAZnNiE8sEafXhrol_Kkg3gmwGgoL8uax7td0w';
const JAR_ID = '3NFVTVCMp';
const RCON_HOST = '107.161.154.161';
const RCON_PORT = 25874;
const RCON_PASSWORD = 'QGtNBbQtt4';

let lastChecked = 0;

function getCommand(nickOriginal, productRaw, type, quantity = 1) {
  const product = productRaw.toLowerCase();

  if (type === 'donate') {
    if (product === 'pan') return `give ${nickOriginal} minecraft:diamond 1`;
    if (product === 'lord') return `lp user ${nickOriginal} parent add lord`;
    if (product === 'sponsor') return `lp user ${nickOriginal} parent add sponsor`;
  }

  if (type === 'case') {
    if (product === 'донат-кейс') return `give ${nickOriginal} minecraft:ender_chest ${quantity}`;
    if (product === 'титул-кейс') return `give ${nickOriginal} minecraft:name_tag ${quantity}`;
  }

  if (type === 'currency') {
    const amount = parseInt(product); // Наприклад: "100" монет
    if (!isNaN(amount)) return `eco give ${nickOriginal} ${amount}`;
  }

  return null;
}

app.get('/check-payment', async (req, res) => {
  try {
    const response = await axios.get(`https://api.monobank.ua/personal/statement/jar/${JAR_ID}/${lastChecked}`, {
      headers: { 'X-Token': MONO_TOKEN }
    });

    const transactions = response.data;
    console.log(`🧾 Отримано транзакцій: ${transactions.length}`);

    for (const tx of transactions) {
      lastChecked = tx.time + 1;
      const comment = tx.comment;
      if (!comment || !comment.includes('|')) continue;

      const parts = comment.split('|').map(p => p.trim());
      if (parts.length < 2) continue;

      const nickOriginal = parts[0];
      const nickLower = nickOriginal.toLowerCase(); // для пошуку
      const product = parts[1];
      const productLower = product.toLowerCase();
      const quantity = parts.length >= 3 ? parseInt(parts[2]) || 1 : 1;

      let type = 'donate';
      if (productLower.includes('кейс')) type = 'case';
      else if (productLower.includes('монет') || !isNaN(parseInt(productLower))) type = 'currency';

      const command = getCommand(nickOriginal, product, type, quantity);
      if (!command) {
        console.log(`⚠️ Невідома команда для продукту "${product}"`);
        continue;
      }

      try {
        const rcon = await Rcon.connect({
          host: RCON_HOST,
          port: RCON_PORT,
          password: RCON_PASSWORD
        });

        await rcon.send(command);
        await rcon.end();

        console.log(`✅ Відправлено: ${command}`);
        return res.json({ status: 'done', command });
      } catch (err) {
        console.error('❌ Помилка при відправці RCON:', err.message);
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

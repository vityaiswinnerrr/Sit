const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const { Rcon } = require('rcon-client');

const app = express();
app.use(bodyParser.json());

const MONO_TOKEN = 'uKHaJC2VisnohHzq2mB4wNrIEd6cWKdebMVNeMtHzHJg';
const JAR_ID = '3NFVTVCMp';

const RCON_HOST = '107.161.154.161'; 
const RCON_PORT = 25847;
const RCON_PASSWORD = 'QGtNBbQtt4';

let lastChecked = 0;


function getCommand(nick, product, type, quantity = 1) {
  product = product.toLowerCase();

  if (type === 'case') {
    switch (product) {
      case 'донат-кейс':
        return `give ${nick} minecraft:ender_chest ${quantity}`;
      case 'валюта-кейс':
        return `give ${nick} minecraft:emerald ${quantity}`;
      case 'титул-кейс':
        return `give ${nick} minecraft:name_tag ${quantity}`;
    }
  }

  if (type === 'currency') {
    switch (product) {
      case '100 монет':
      case '250 монет':
      case '500 монет':
      case '1000 монет':
        const amount = parseInt(product.split(' ')[0]); 
        return `eco give ${nick} ${amount}`;
    }
  }

  if (type === 'donate') {
    switch (product) {
      case 'pan':
        return `give ${nick} minecraft:diamond 1`;
      case 'lord':
      case 'knyaz':
      case 'imperator':
      case 'fantom':
      case 'sponsor':
      case 'sumer':
      case 'titan':
      case 'god':
      case 'premium':
        return `lp user ${nick} parent add ${product}`;
    }
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

    for (const tx of transactions) {
      lastChecked = tx.time + 1;

      const comment = tx.comment;
      if (!comment || !comment.includes('|')) continue;

      const [nickRaw, productRaw, quantityRaw] = comment.split('|');
      const nick = nickRaw?.trim();
      const product = productRaw?.trim();
      const quantity = parseInt(quantityRaw) || 1;

      let type = 'donate';
      const productLower = product.toLowerCase();
      if (productLower.includes('кейс')) type = 'case';
      else if (productLower.includes('монет')) type = 'currency';

      if (!nick || !product) continue;

      const command = getCommand(nick, product, type, quantity);
      if (!command) continue;

      try {
        const rcon = await Rcon.connect({
          host: RCON_HOST,
          port: RCON_PORT,
          password: RCON_PASSWORD
        });

        await rcon.send(command);
        await rcon.end();

        console.log(` Команда відправлена: ${command}`);
        return res.json({ status: 'done', command });
      } catch (err) {
        console.error("❌ Помилка RCON:", err.message);
        return res.status(500).json({ status: 'error', error: err.message });
      }
    }

    res.json({ status: 'wait' });
  } catch (e) {
    console.error(" Помилка Monobank:", e.message);
    res.status(500).json({ status: 'error', error: e.message });
  }
});


app.post('/api/give', async (req, res) => {
  const { nick, product, type, quantity } = req.body;

  const command = getCommand(nick, product, type, quantity || 1);
  if (!command) return res.status(400).json({ status: 'error', error: 'Unknown product' });

  try {
    const rcon = await Rcon.connect({
      host: RCON_HOST,
      port: RCON_PORT,
      password: RCON_PASSWORD
    });

    await rcon.send(command);
    await rcon.end();

    res.json({ status: 'done', command });
  } catch (err) {
    console.error(" Помилка RCON:", err.message);
    res.status(500).json({ status: 'error', error: err.message });
  }
});

app.listen(3000, () => {
  console.log(" Сервер запущено на порту 3000");
});

const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const dotenv = require('dotenv');
const cloudinary = require('cloudinary').v2;
const multer = require('multer');
const { CloudinaryStorage } = require('multer-storage-cloudinary');

dotenv.config();

const app = express();
app.use(express.json({ limit: '50mb' }));
app.use(cors({ origin: '*' }));

// Cloudinary
cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET
});

const storage = new CloudinaryStorage({
  cloudinary: cloudinary,
  params: { folder: 'pornoxram', resource_type: 'auto' }
});
const upload = multer({ storage });

// Модели
const Model = mongoose.model('Model', new mongoose.Schema({
  name_ru: String, name_en: String, photo_url: String, createdAt: { type: Date, default: Date.now }
}));

const Video = mongoose.model('Video', new mongoose.Schema({
  title_ru: String, title_en: String,
  description_ru: String, description_en: String,
  video_url: String, thumbnail_url: String,
  models: [{ type: mongoose.Schema.Types.ObjectId, ref: 'Model' }],
  hashtags: [String],
  createdAt: { type: Date, default: Date.now }
}));

mongoose.connect(process.env.MONGO_URI);

// Middleware
function isAdmin(req, res, next) {
  const user = req.body.user ? JSON.parse(req.body.user) : null;
  if (!user || user.id != process.env.ADMIN_USER_ID) return res.status(403).json({ error: 'Access denied' });
  req.tgUser = user;
  next();
}

// Публичные API
app.get('/api/models', async (req, res) => {
  const models = await Model.find().sort({ createdAt: -1 });
  res.json(models);
});

app.get('/api/videos/model/:modelId', async (req, res) => {
  const videos = await Video.find({ models: req.params.modelId }).populate('models').sort({ createdAt: -1 });
  res.json(videos);
});

app.get('/api/hashtags', async (req, res) => {
  const videos = await Video.find({}, 'hashtags');
  const tags = [...new Set(videos.flatMap(v => v.hashtags || []))].filter(Boolean);
  res.json(tags);
});

app.get('/api/videos/hashtag/:tag', async (req, res) => {
  const videos = await Video.find({ hashtags: req.params.tag }).populate('models').sort({ createdAt: -1 });
  res.json(videos);
});

app.get('/api/search', async (req, res) => {
  const q = req.query.q || '';
  const models = await Model.find({ $or: [{ name_ru: new RegExp(q, 'i') }, { name_en: new RegExp(q, 'i') }] });
  const videos = await Video.find({ $or: [{ title_ru: new RegExp(q, 'i') }, { title_en: new RegExp(q, 'i') }] }).populate('models');
  res.json({ models, videos });
});

// Админ API
app.post('/api/admin/model', isAdmin, upload.single('photo'), async (req, res) => {
  const { name_ru, name_en } = req.body;
  const model = new Model({ name_ru, name_en, photo_url: req.file.path });
  await model.save();
  res.json(model);
});

app.post('/api/admin/video', isAdmin, upload.single('video'), async (req, res) => {
  const { title_ru, title_en, description_ru, description_en, modelIds, hashtags } = req.body;
  const video = new Video({
    title_ru, title_en, description_ru, description_en,
    video_url: req.file.path,
    thumbnail_url: cloudinary.url(req.file.filename, { transformation: [{ width: 600, crop: 'fill' }] }),
    models: modelIds ? modelIds.split(',').map(id => id.trim()) : [],
    hashtags: hashtags ? hashtags.split(',').map(t => t.trim()) : []
  });
  await video.save();
  res.json(video);
});

app.delete('/api/admin/model/:id', isAdmin, async (req, res) => {
  await Model.findByIdAndDelete(req.params.id);
  res.json({ success: true });
});

app.delete('/api/admin/video/:id', isAdmin, async (req, res) => {
  await Video.findByIdAndDelete(req.params.id);
  res.json({ success: true });
});

// Донат Stars
app.post('/api/create-invoice', async (req, res) => {
  const { amount } = req.body;
  try {
    const response = await fetch(`https://api.telegram.org/bot${process.env.BOT_TOKEN}/createInvoiceLink`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: "Поддержка PornoXram",
        description: `Пожертвование ${amount} Stars`,
        payload: `donate_${Date.now()}`,
        currency: 'XTR',
        prices: [{ label: `${amount} Stars`, amount: parseInt(amount) }]
      })
    });
    const data = await response.json();
    if (data.ok) res.json({ invoice_link: data.result });
    else res.status(500).json({ error: data.description });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`PornoXram Backend запущен на порту ${PORT}`));

# 🚀 Configuration Coolify - Dashboard Vianova

## Setup du sous-domaine `dashboard.meninbot.com`

### 1. **Dans Coolify**

1. **Créer une nouvelle Application**
   - Nom: `vianova-dashboard`
   - Type: `Docker`

2. **Repository Settings**
   - GitHub/Git URL: (ton repo avec le code)
   - Branch: `main`
   - Dockerfile: `Dockerfile`

3. **Domain Settings**
   - Domain: `dashboard.meninbot.com`
   - Port: `5000`
   - SSL: ✅ Activé (Let's Encrypt auto)

4. **Environment Variables**
   ```
   FLASK_ENV=production
   FLASK_DEBUG=0
   ```

5. **Build & Deploy**
   - Clique sur "Deploy"
   - Coolify build l'image Docker et la déploie

### 2. **DNS Configuration**

Chez ton registrar (GoDaddy, OVH, etc.) :

```
dashboard   CNAME   187.124.33.83
```

Ou avec ton loadbalancer Coolify :
```
dashboard   CNAME   coolify.meninbot.com
```

### 3. **Vérification**

```bash
# Test que le domaine fonctionne
curl https://dashboard.meninbot.com/api/health

# Doit retourner:
{
  "status": "ok",
  "services": {...}
}
```

### 4. **Fichiers Coolify**

- `docker-compose.yml` ✅ (créé)
- `Dockerfile` ✅ (créé)
- `requirements.txt` ✅ (existant)
- Tous les autres fichiers ✅

---

## Architecture

```
meninbot.com
    ├── Site principal (existant)
    └── dashboard.meninbot.com → Port 5000 (Vianova)
```

---

## Support

Si tu as des questions sur Coolify:
- Docs: https://coolify.io
- Support: https://discord.gg/CqzMVbR5

Dis-moi quand tu as configuré le DNS et je teste l'accès ! 🚀

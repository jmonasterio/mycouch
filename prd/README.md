# Product Requirements Documents

This folder contains all Product Requirements Documents for the CouchDB JWT Proxy project.

## Documents

### Core PRDs

- **[PRD.md](./PRD.md)** - Main product requirements
  - Overall proxy vision and goals
  - Core features and functionality
  - Architecture overview

- **[PRD-jwt-proxy.md](./PRD-jwt-proxy.md)** - JWT authentication strategy
  - Clerk JWT support (RS256)
  - Custom JWT support (HS256)
  - Fallback authentication flow
  - Token validation logic

- **[prd-tenant-creation.md](./prd-tenant-creation.md)** - Multi-tenant data model
  - Tenant auto-creation on first login
  - CouchDB document structure
  - Tenant isolation strategy
  - Future extensions (invitations, role management)

## Reading Order

For understanding the project:

1. **PRD.md** - High-level vision
2. **PRD-jwt-proxy.md** - Authentication strategy
3. **prd-tenant-creation.md** - Data model and tenant isolation

## Related Documentation

- See `../docs/` for deployment and setup guides
- See `../README.md` for user-facing documentation
- See `../CLAUDE.md` for development context

# Sample Ontology

A complete, valid example of the extraction ontology JSON consumed by
`app/ontology.py` (`ontology_from_doc`) and the auto-tune flow in
`app/ontology_autotune.py`. This sample models a **SaaS / product company**
domain and satisfies every rule in `validate_ontology()`:

- at least one entity type
- unique names per kind (entity / edge)
- every type has a non-empty `description`
- every type has at least one required (`optional: false`) field
- entity types include a required `description` field; edge types include a
  required `rationale` field plus a PascalCase `title` and UPPER_SNAKE `name`
- a generic `RELATES_TO` edge and a `Concept` residual entity bucket exist
- every `edge_type_map` subject/object is a defined entity type and every edge
  is a defined edge type

## Schema at a glance

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Ontology registry key |
| `version` | string | e.g. `v1` |
| `entity_types` | `OntologyType[]` | ≥ 1 required |
| `edge_types` | `OntologyType[]` | relationship types |
| `edge_type_map` | `{subject, object, edges[]}[]` | allowed edges between entity types |
| `instructions` | string | appended to the extractor system prompt |

`OntologyType`: `{ name, title?, description, fields[] }`
`OntologyField`: `{ name, description?, optional, default? }`

## Sample (JSON)

```json
{
  "name": "saas_company",
  "version": "v1",
  "entity_types": [
    {
      "name": "Person",
      "description": "A human individual such as an employee, founder, customer contact, or investor.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing this person and why they matter in context.",
          "optional": false
        },
        {
          "name": "role",
          "description": "The person's role or title, e.g. 'VP of Engineering', 'Account Executive'.",
          "optional": true
        },
        {
          "name": "affiliation",
          "description": "Organization the person is associated with.",
          "optional": true
        }
      ]
    },
    {
      "name": "Organization",
      "description": "A company, customer, partner, competitor, or investor entity.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing what this organization does and its relevance.",
          "optional": false
        },
        {
          "name": "kind",
          "description": "One of: vendor, customer, partner, competitor, investor, other.",
          "optional": true
        }
      ]
    },
    {
      "name": "Product",
      "description": "A software product, application, or service offered by an organization.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing the product and its purpose.",
          "optional": false
        },
        {
          "name": "category",
          "description": "Product category, e.g. 'CRM', 'observability', 'data platform'.",
          "optional": true
        }
      ]
    },
    {
      "name": "Feature",
      "description": "A specific capability, module, or feature of a product.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing what the feature does.",
          "optional": false
        },
        {
          "name": "status",
          "description": "Lifecycle status, e.g. 'GA', 'beta', 'planned', 'deprecated'.",
          "optional": true
        }
      ]
    },
    {
      "name": "Technology",
      "description": "A language, framework, database, cloud service, or other technical building block.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing the technology and how it is used.",
          "optional": false
        },
        {
          "name": "kind",
          "description": "One of: language, framework, database, service, library, protocol, other.",
          "optional": true
        }
      ]
    },
    {
      "name": "Team",
      "description": "An internal organizational unit such as a squad, department, or function.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing the team's mission or area of ownership.",
          "optional": false
        }
      ]
    },
    {
      "name": "Event",
      "description": "A time-anchored occurrence such as a launch, incident, funding round, or release.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing the event and its significance.",
          "optional": false
        },
        {
          "name": "when",
          "description": "Free-text time anchor as it appears in the source.",
          "optional": true
        }
      ]
    },
    {
      "name": "Metric",
      "description": "A quantitative business or engineering measure such as ARR, latency, or churn.",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing what the metric measures.",
          "optional": false
        },
        {
          "name": "unit",
          "description": "Unit or currency, e.g. 'USD', 'ms', 'percent'.",
          "optional": true
        }
      ]
    },
    {
      "name": "Concept",
      "description": "A general topic, methodology, or idea used only when no more specific type fits (residual bucket).",
      "fields": [
        {
          "name": "description",
          "description": "One short sentence describing the concept and how it relates to the source.",
          "optional": false
        }
      ]
    }
  ],
  "edge_types": [
    {
      "name": "WORKS_FOR",
      "title": "WorksFor",
      "description": "A person is employed by or affiliated with an organization.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        },
        { "name": "role", "optional": true }
      ]
    },
    {
      "name": "MEMBER_OF",
      "title": "MemberOf",
      "description": "A person belongs to an internal team.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "BUILDS",
      "title": "Builds",
      "description": "An organization or team builds, owns, or maintains a product.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "HAS_FEATURE",
      "title": "HasFeature",
      "description": "A product includes or exposes a feature.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "USES",
      "title": "Uses",
      "description": "A product, feature, or team uses a technology.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "INTEGRATES_WITH",
      "title": "IntegratesWith",
      "description": "A product integrates or interoperates with another product.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "COMPETES_WITH",
      "title": "CompetesWith",
      "description": "An organization competes with another organization.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "MEASURES",
      "title": "Measures",
      "description": "A metric measures a product, feature, or organization.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    },
    {
      "name": "RELATES_TO",
      "title": "RelatesTo",
      "description": "Generic semantic relation when no more specific edge type fits.",
      "fields": [
        {
          "name": "rationale",
          "description": "One short clause justifying this relationship from the text.",
          "optional": false
        }
      ]
    }
  ],
  "edge_type_map": [
    { "subject": "Person", "object": "Organization", "edges": ["WORKS_FOR", "RELATES_TO"] },
    { "subject": "Person", "object": "Team", "edges": ["MEMBER_OF", "RELATES_TO"] },
    { "subject": "Organization", "object": "Product", "edges": ["BUILDS", "RELATES_TO"] },
    { "subject": "Team", "object": "Product", "edges": ["BUILDS", "RELATES_TO"] },
    { "subject": "Product", "object": "Feature", "edges": ["HAS_FEATURE", "RELATES_TO"] },
    { "subject": "Product", "object": "Technology", "edges": ["USES", "RELATES_TO"] },
    { "subject": "Feature", "object": "Technology", "edges": ["USES", "RELATES_TO"] },
    { "subject": "Team", "object": "Technology", "edges": ["USES", "RELATES_TO"] },
    { "subject": "Product", "object": "Product", "edges": ["INTEGRATES_WITH", "RELATES_TO"] },
    { "subject": "Organization", "object": "Organization", "edges": ["COMPETES_WITH", "RELATES_TO"] },
    { "subject": "Metric", "object": "Product", "edges": ["MEASURES", "RELATES_TO"] },
    { "subject": "Metric", "object": "Organization", "edges": ["MEASURES", "RELATES_TO"] }
  ],
  "instructions": "Prefer specific entity types over the generic Concept fallback. Use Product for named applications or services, Feature for capabilities within a product, and Technology for languages, frameworks, databases, or cloud services. Use Metric for quantitative measures like ARR, latency, or churn. Only use Concept when none of the more specific types fit. For relationships, prefer specific edge types and only fall back to RELATES_TO when no specific type describes the relation."
}
```

## Notes

- **Entity type names** are PascalCase; **edge type names** are UPPER_SNAKE with
  a PascalCase `title` (the rebuilt Pydantic model / JSON-schema class name).
- Each type carries at least one required field so the rebuilt Cohere
  `json_schema` is valid (BUG-010). For entity types that field is `description`;
  for edge types it is `rationale`.
- `edge_type_map` is directional: `subject` → `object`. Add both directions
  explicitly if a relationship is meaningful either way.
- The runtime store of record is the DB `prompt_sets` table. Config-as-code
  seeds live in `app/ontologies/<name>_<version>.yaml` (same schema, YAML form).
```

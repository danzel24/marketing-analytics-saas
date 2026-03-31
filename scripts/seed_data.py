from __future__ import annotations

import random
from datetime import date, timedelta

from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
from app.models.db_models import Campaign, CampaignMetric, Client


def seed_demo_data() -> None:
    create_db_and_tables()

    with Session(engine) as session:
        # 1) Demo client
        client = session.exec(select(Client).where(Client.name == "demo")).first()
        if not client:
            client = Client(name="demo")
            session.add(client)
            session.commit()
            session.refresh(client)

        # 2) Campaigns
        campaign_names = [
            ("facebook_ads", "facebook"),
            ("google_ads", "google"),
            ("tiktok_ads", "tiktok"),
        ]

        campaigns: list[Campaign] = []
        for name, platform in campaign_names:
            existing = session.exec(
                select(Campaign).where(
                    Campaign.name == name,
                    Campaign.client_id == client.id,  # type: ignore[arg-type]
                )
            ).first()
            if existing:
                campaigns.append(existing)
                continue

            camp = Campaign(
                name=name,
                platform=platform,
                client_id=client.id,  # type: ignore[arg-type]
            )
            session.add(camp)
            session.commit()
            session.refresh(camp)
            campaigns.append(camp)

        # 3) 30 dní metrik pro každou kampaň
        today = date.today()
        days = 30

        for camp in campaigns:
            for i in range(days):
                metric_date = today - timedelta(days=i)

                # Zkontroluj, zda už pro tento den a kampaň existuje záznam
                exists = session.exec(
                    select(CampaignMetric).where(
                        CampaignMetric.campaign_id == camp.id,
                        CampaignMetric.metric_date == metric_date,
                    )
                ).first()
                if exists:
                    continue

                spend = random.uniform(50, 200)
                clicks = random.randint(100, 400)
                conversions = random.randint(5, 30)
                multiplier = random.uniform(1.5, 3.5)
                revenue = spend * multiplier

                metric = CampaignMetric(
                    campaign_id=camp.id,  # type: ignore[arg-type]
                    metric_date=metric_date,
                    spend=round(spend, 2),
                    revenue=round(revenue, 2),
                    clicks=clicks,
                    conversions=conversions,
                )
                session.add(metric)

        session.commit()


def main() -> None:
    seed_demo_data()
    print("Demo data seeded into marketing.db")


if __name__ == "__main__":
    main()


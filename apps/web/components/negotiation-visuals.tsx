import { demoScenarios, initialMessagesForScenario } from "../lib/demo-data";

const equipmentScenario = demoScenarios[0];
const openingMessage = initialMessagesForScenario(equipmentScenario.id)[1].text;

/** A short excerpt from the supplied training case, presented as an interface preview. */
export function HeroConversationPreview() {
  return (
    <figure className="home-hero-art home-conversation-preview" aria-label="Пример диалога в кейсе «Поставка оборудования»">
      <div className="conversation-preview-frame">
        <div className="conversation-preview-header">
          <span className="conversation-preview-mark" aria-hidden="true">↗</span>
          <div>
            <span className="conversation-preview-overline">Пример тренировки</span>
            <strong>{equipmentScenario.title}</strong>
          </div>
          <span className="conversation-preview-format">Текст</span>
        </div>
        <div className="conversation-preview-transcript">
          <div className="conversation-preview-turn conversation-preview-turn--opponent">
            <span className="conversation-preview-speaker">Поставщик</span>
            <p>{openingMessage}</p>
          </div>
          <div className="conversation-preview-turn conversation-preview-turn--participant">
            <span className="conversation-preview-speaker">Вы</span>
            <p>И что важнее сохранить — цену или срок поставки?</p>
          </div>
        </div>
        <div className="conversation-preview-footnote">
          <span className="conversation-preview-skill-mark" aria-hidden="true">✓</span>
          <span>Навык в фрагменте: исследование интересов</span>
        </div>
      </div>
    </figure>
  );
}

export function TrainingFlow() {
  return (
    <section className="home-training-flow" aria-labelledby="home-training-flow-title">
      <div className="home-training-flow-heading">
        <span className="eyebrow">Как это работает</span>
        <h2 id="home-training-flow-title">От кейса до следующей сильной реплики</h2>
      </div>
      <div className="home-training-flow-steps">
        <article>
          <span className="home-training-flow-number">01</span>
          <h3>Выберите ситуацию</h3>
          <p>Возьмите готовый кейс или задайте свои условия.</p>
        </article>
        <article>
          <span className="home-training-flow-number">02</span>
          <h3>Проведите диалог</h3>
          <p>Тренируйтесь с AI-оппонентом голосом или текстом.</p>
        </article>
        <article>
          <span className="home-training-flow-number">03</span>
          <h3>Разберите решения</h3>
          <p>Увидите удачные приёмы, ошибки и вариант следующего шага.</p>
        </article>
      </div>
    </section>
  );
}

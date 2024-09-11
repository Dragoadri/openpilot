
#include "selfdrive/ui/qt/onroad/annotated_camera.h"

#include <QPainter>
#include <algorithm>
#include <cmath>

#include "common/swaglog.h"
#include "selfdrive/ui/qt/onroad/buttons.h"
#include "selfdrive/ui/qt/util.h"

//Adrian Cañadas Gallardo
#include <QPixmap>
#include <QRect>
float v_egoo=0;
float a_egoo=0;
float steeringAngleDeg=0;
float combustible=0;
bool LeftBlinker = false;
bool RightBlinker = false;

// Window that shows camera view and variety of info drawn on top
AnnotatedCameraWidget::AnnotatedCameraWidget(VisionStreamType type, QWidget* parent) : fps_filter(UI_FREQ, 3, 1. / UI_FREQ), CameraWidget("camerad", type, true, parent) {
  pm = std::make_unique<PubMaster, const std::initializer_list<const char *>>({"uiDebug"});

  main_layout = new QVBoxLayout(this);
  main_layout->setMargin(UI_BORDER_SIZE);
  main_layout->setSpacing(0);

  experimental_btn = new ExperimentalButton(this);
  main_layout->addWidget(experimental_btn, 0, Qt::AlignTop | Qt::AlignRight);

  dm_img = loadPixmap("../assets/img_driver_face.png", {img_size + 5, img_size + 5});
}

void AnnotatedCameraWidget::updateState(const UIState &s) {
  const int SET_SPEED_NA = 255;
  const SubMaster &sm = *(s.sm);

  const bool cs_alive = sm.alive("controlsState");
  const auto cs = sm["controlsState"].getControlsState();
  const auto car_state = sm["carState"].getCarState();

  is_metric = s.scene.is_metric;
   //Adrian Cañadas Gallardo
  is_activateEvent = s.scene.is_activateEvent;

  // Handle older routes where vCruiseCluster is not set
  float v_cruise = cs.getVCruiseCluster() == 0.0 ? cs.getVCruise() : cs.getVCruiseCluster();
  setSpeed = cs_alive ? v_cruise : SET_SPEED_NA;
  is_cruise_set = setSpeed > 0 && (int)setSpeed != SET_SPEED_NA;
  if (is_cruise_set && !is_metric) {
    setSpeed *= KM_TO_MILE;
  }

  // Handle older routes where vEgoCluster is not set
  v_ego_cluster_seen = v_ego_cluster_seen || car_state.getVEgoCluster() != 0.0;
  float v_ego = v_ego_cluster_seen ? car_state.getVEgoCluster() : car_state.getVEgo();

   //Adrian Cañadas Gallardo
  float a_ego = car_state.getAEgo();
  v_egoo = v_ego;
  a_egoo = a_ego;
  steeringAngleDeg = car_state.getSteeringAngleDeg();
  combustible = car_state.getFuelGauge();//Devuelve de 0 a 1 asiq ue haremos el porcentaje
  LeftBlinker = car_state.getLeftBlinker();
  RightBlinker = car_state.getRightBlinker();


  
  speed = cs_alive ? std::max<float>(0.0, v_ego) : 0.0;
  speed *= is_metric ? MS_TO_KPH : MS_TO_MPH;

  speedUnit = is_metric ? tr("km/h") : tr("mph");
  hideBottomIcons = (cs.getAlertSize() != cereal::ControlsState::AlertSize::NONE);
  status = s.status;

  // update engageability/experimental mode button
  experimental_btn->updateState(s);

  // update DM icon
  auto dm_state = sm["driverMonitoringState"].getDriverMonitoringState();
  dmActive = dm_state.getIsActiveMode();
  rightHandDM = dm_state.getIsRHD();
  // DM icon transition
  dm_fade_state = std::clamp(dm_fade_state+0.2*(0.5-dmActive), 0.0, 1.0);
}

void AnnotatedCameraWidget::drawHud(QPainter &p) {
  p.save();

  

 if(is_activateEvent){
   QLinearGradient bg(0, UI_HEADER_HEIGHT - (UI_HEADER_HEIGHT / 2.5), 0, UI_HEADER_HEIGHT);
  bg.setColorAt(0, QColor::fromRgbF(0, 0, 0, 0.45));
  bg.setColorAt(1, QColor::fromRgbF(0, 0, 0, 0));
  p.fillRect(0, 0, width(), UI_HEADER_HEIGHT, bg);

  QString speedStr = is_cruise_set ? QString::number(std::nearbyint(speed)) : "-";
  QString setSpeedStr = is_cruise_set ? QString::number(std::nearbyint(setSpeed)) : "-";

//Adrian Cañadas Gallardo
  QString v_egoStr =  is_cruise_set ? QString::number(std::nearbyint(v_egoo)) : "-";
    QString acelStr =  is_cruise_set ? QString::number(std::nearbyint(a_egoo)) : "-";



  //Adrian Cañadas Gallardo MAX velocidad

  // Draw outer box + border to contain set speed
  const QSize default_size = {172, 204};
  QSize set_speed_size = default_size;

  if (is_metric) set_speed_size.rwidth() = 200;

 // Definir colores
QColor max_color = QColor(0x80, 0xd8, 0xa6, 0xff);
QColor set_speed_color = whiteColor();
//QColor label_color = whiteColor(); // Color para las etiquetas

// Configurar colores basados en el estado del crucero
if (is_cruise_set) {
    if (status == STATUS_DISENGAGED) {
        max_color = whiteColor();
    } else if (status == STATUS_OVERRIDE) {
        max_color = QColor(0x91, 0x9b, 0x95, 0xff);

    }
} else {
    max_color = QColor(0xa6, 0xa6, 0xa6, 0xff);
    set_speed_color = QColor(0x72, 0x72, 0x72, 0xff);
}

// Configurar fuente para las etiquetas y valores
QFont labelFont("Inter", 7, QFont::DemiBold); // Tamaño más pequeño para etiquetas
QFont valueFont("Inter", 7, QFont::Bold); // Tamaño más pequeño para valores

// Establecer posiciones y ajustar el rectángulo



// Ajustar el rectángulo negro (o fondo) para cada texto
int rectWidth = 100; // Ajustar el ancho del rectángulo según sea necesario
int rectHeight = 750; // Ajustar la altura del rectángulo según sea necesario

int xOffset = 100-rectWidth; // Ajusta el margen izquierdo
//int xIncrement = 100; // Espaciado entre columnas

int yOffset = 100-rectHeight; // Ajusta el margen superior
int yIncrement = 100; // Espaciado entre líneas

QRect set_speed_rect(QPoint(60, 45), QSize(rectWidth, rectHeight));

// Dibujar el rectángulo negro de fondo
p.setPen(QPen(whiteColor(75), 6));
p.setBrush(blackColor(166));
p.drawRoundedRect(set_speed_rect, 32, 32);

// Configurar fuente y dibujar textos
p.setFont(labelFont);

// DIBUJAR SICUEM


// DIBUJAR SICUEM
QRect text_rect = set_speed_rect.adjusted(xOffset, yOffset -20, 0, 0);
//Color rojo
p.setPen(QColor(255, 0, 0, 255));
p.setFont(labelFont);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("SICUEM"));

// Cargar la imagen
QPixmap imagen("../assets/offroad/alerta.png"); // Cambia la ruta a la ubicación de tu imagen

// Obtener el tamaño de la imagen
int imagenAncho = imagen.width();
int imagenAlto = imagen.height();

//int centerX = width() / 2;
//int centerY = height() / 2;

// Definir la posición para dibujar la imagen debajo del texto
QRect imagen_rect = QRect(xOffset+85, yOffset*2+text_rect.height() - 10, imagenAncho/3.25, imagenAlto/3.25); // Ajusta el 10 para el espacio entre el texto y la imagen

// Dibujar la imagen
p.drawPixmap(imagen_rect, imagen);

// MAX
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 2 * yIncrement, 0, 0);
p.setPen(max_color);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("MAX"));

// Set Speed
p.setFont(valueFont);
p.setPen(set_speed_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 3 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, setSpeedStr);

// Veloc d
p.setFont(labelFont);
p.setPen(max_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 4 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("Vel. MAX"));

p.setFont(valueFont);
p.setPen(set_speed_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 5 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, speedStr + " " + speedUnit);

// Veloc r
p.setFont(labelFont);
p.setPen(max_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 6 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("Vel REAL"));

p.setFont(valueFont);
p.setPen(set_speed_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 7 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, v_egoStr + " " + speedUnit);

// acel
p.setFont(labelFont);
p.setPen(max_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 8 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("Acel."));

p.setFont(valueFont);
p.setPen(set_speed_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 9 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, acelStr + " m/s²");

// Angulo
p.setFont(labelFont);
p.setPen(max_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 10 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("Angulo"));

p.setFont(valueFont);
p.setPen(set_speed_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 11 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, QString::number(steeringAngleDeg) + " °");

// Combustible
p.setFont(labelFont);
p.setPen(max_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 12 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, tr("FUEL ⛽"));

p.setFont(valueFont);
p.setPen(set_speed_color);
text_rect = set_speed_rect.adjusted(xOffset, yOffset + 13 * yIncrement, 0, 0);
p.drawText(text_rect, Qt::AlignHCenter | Qt::AlignVCenter, QString::number(combustible*100) + " %");





  //Adrian Cañadas Gallardo

  // Ajustar el rectángulo negro (o fondo) para cada texto
int rectWidth2 = 300; // Ajustar el ancho del rectángulo según sea necesario
int rectHeight2 = 300; // Ajustar la altura del rectángulo según sea necesario




QRect set_speed_rect2(QPoint(1775, 700), QSize(rectWidth2, rectHeight2));
// Dibujar el rectángulo negrrectHeighto de fondo
p.setPen(QPen(whiteColor(75), 6));
p.setBrush(blackColor(166));
p.drawRoundedRect(set_speed_rect2, 32, 32);

// Configurar fuente y dibujar textos
p.setFont(labelFont);



    QPixmap imagen2(LeftBlinker?"./assets/offroad/blinkers_left.png" : RightBlinker?"../assets/offroad/blinkers_rigth.png":"../assets/offroad/blinkers.png"); // Path to your image
    int imagen2Ancho = imagen2.width();
    int imagen2Alto = imagen2.height();
    int image2Width = imagen2Ancho / 3.25;
    int image2Height = imagen2Alto / 3.25;


    QRect imagen2_rect(width() - image2Width- 200 / 2, height() - image2Height - 200 / 2, image2Width, image2Height);
    p.drawPixmap(imagen2_rect, imagen2);
}


  p.restore();
}

void AnnotatedCameraWidget::drawText(QPainter &p, int x, int y, const QString &text, int alpha) {
  QRect real_rect = p.fontMetrics().boundingRect(text);
  real_rect.moveCenter({x, y - real_rect.height() / 2});

  p.setPen(QColor(0xff, 0xff, 0xff, alpha));
  p.drawText(real_rect.x(), real_rect.bottom(), text);
}

void AnnotatedCameraWidget::initializeGL() {
  CameraWidget::initializeGL();
  qInfo() << "OpenGL version:" << QString((const char*)glGetString(GL_VERSION));
  qInfo() << "OpenGL vendor:" << QString((const char*)glGetString(GL_VENDOR));
  qInfo() << "OpenGL renderer:" << QString((const char*)glGetString(GL_RENDERER));
  qInfo() << "OpenGL language version:" << QString((const char*)glGetString(GL_SHADING_LANGUAGE_VERSION));

  prev_draw_t = millis_since_boot();
  setBackgroundColor(bg_colors[STATUS_DISENGAGED]);
}

void AnnotatedCameraWidget::updateFrameMat() {
  CameraWidget::updateFrameMat();
  UIState *s = uiState();
  int w = width(), h = height();

  s->fb_w = w;
  s->fb_h = h;

  // Apply transformation such that video pixel coordinates match video
  // 1) Put (0, 0) in the middle of the video
  // 2) Apply same scaling as video
  // 3) Put (0, 0) in top left corner of video
  s->car_space_transform.reset();
  s->car_space_transform.translate(w / 2 - x_offset, h / 2 - y_offset)
      .scale(zoom, zoom)
      .translate(-intrinsic_matrix.v[2], -intrinsic_matrix.v[5]);
}

void AnnotatedCameraWidget::drawLaneLines(QPainter &painter, const UIState *s) {
  painter.save();

  const UIScene &scene = s->scene;
  SubMaster &sm = *(s->sm);

  // lanelines
  for (int i = 0; i < std::size(scene.lane_line_vertices); ++i) {
    painter.setBrush(QColor::fromRgbF(1.0, 1.0, 1.0, std::clamp<float>(scene.lane_line_probs[i], 0.0, 0.7)));
    painter.drawPolygon(scene.lane_line_vertices[i]);
  }

  // road edges
  for (int i = 0; i < std::size(scene.road_edge_vertices); ++i) {
    painter.setBrush(QColor::fromRgbF(1.0, 0, 0, std::clamp<float>(1.0 - scene.road_edge_stds[i], 0.0, 1.0)));
    painter.drawPolygon(scene.road_edge_vertices[i]);
  }

  // paint path
  QLinearGradient bg(0, height(), 0, 0);
  if (sm["controlsState"].getControlsState().getExperimentalMode()) {
    // The first half of track_vertices are the points for the right side of the path
    const auto &acceleration = sm["modelV2"].getModelV2().getAcceleration().getX();
    const int max_len = std::min<int>(scene.track_vertices.length() / 2, acceleration.size());

    for (int i = 0; i < max_len; ++i) {
      // Some points are out of frame
      int track_idx = (scene.track_vertices.length() / 2) - i;  // flip idx to start from top
      if (scene.track_vertices[track_idx].y() < 0 || scene.track_vertices[track_idx].y() > height()) continue;

      // Flip so 0 is bottom of frame
      float lin_grad_point = (height() - scene.track_vertices[track_idx].y()) / height();

      // speed up: 120, slow down: 0
      float path_hue = fmax(fmin(60 + acceleration[i] * 35, 120), 0);
      // FIXME: painter.drawPolygon can be slow if hue is not rounded
      path_hue = int(path_hue * 100 + 0.5) / 100;

      float saturation = fmin(fabs(acceleration[i] * 1.5), 1);
      float lightness = util::map_val(saturation, 0.0f, 1.0f, 0.95f, 0.62f);  // lighter when grey
      float alpha = util::map_val(lin_grad_point, 0.75f / 2.f, 0.75f, 0.4f, 0.0f);  // matches previous alpha fade
      bg.setColorAt(lin_grad_point, QColor::fromHslF(path_hue / 360., saturation, lightness, alpha));

      // Skip a point, unless next is last
      i += (i + 2) < max_len ? 1 : 0;
    }

  } else {
    bg.setColorAt(0.0, QColor::fromHslF(148 / 360., 0.94, 0.51, 0.4));
    bg.setColorAt(0.5, QColor::fromHslF(112 / 360., 1.0, 0.68, 0.35));
    bg.setColorAt(1.0, QColor::fromHslF(112 / 360., 1.0, 0.68, 0.0));
  }

  painter.setBrush(bg);
  painter.drawPolygon(scene.track_vertices);

  painter.restore();
}

void AnnotatedCameraWidget::drawDriverState(QPainter &painter, const UIState *s) {
  const UIScene &scene = s->scene;

  painter.save();

  // base icon
  int offset = UI_BORDER_SIZE + btn_size / 2;
  int x = rightHandDM ? width() - offset : offset;
  int y = height() - offset;
  float opacity = dmActive ? 0.65 : 0.2;
  drawIcon(painter, QPoint(x, y), dm_img, blackColor(70), opacity);

  // face
  QPointF face_kpts_draw[std::size(default_face_kpts_3d)];
  float kp;
  for (int i = 0; i < std::size(default_face_kpts_3d); ++i) {
    kp = (scene.face_kpts_draw[i].v[2] - 8) / 120 + 1.0;
    face_kpts_draw[i] = QPointF(scene.face_kpts_draw[i].v[0] * kp + x, scene.face_kpts_draw[i].v[1] * kp + y);
  }

  painter.setPen(QPen(QColor::fromRgbF(1.0, 1.0, 1.0, opacity), 5.2, Qt::SolidLine, Qt::RoundCap));
  painter.drawPolyline(face_kpts_draw, std::size(default_face_kpts_3d));

  // tracking arcs
  const int arc_l = 133;
  const float arc_t_default = 6.7;
  const float arc_t_extend = 12.0;
  QColor arc_color = QColor::fromRgbF(0.545 - 0.445 * s->engaged(),
                                      0.545 + 0.4 * s->engaged(),
                                      0.545 - 0.285 * s->engaged(),
                                      0.4 * (1.0 - dm_fade_state));
  float delta_x = -scene.driver_pose_sins[1] * arc_l / 2;
  float delta_y = -scene.driver_pose_sins[0] * arc_l / 2;
  painter.setPen(QPen(arc_color, arc_t_default+arc_t_extend*fmin(1.0, scene.driver_pose_diff[1] * 5.0), Qt::SolidLine, Qt::RoundCap));
  painter.drawArc(QRectF(std::fmin(x + delta_x, x), y - arc_l / 2, fabs(delta_x), arc_l), (scene.driver_pose_sins[1]>0 ? 90 : -90) * 16, 180 * 16);
  painter.setPen(QPen(arc_color, arc_t_default+arc_t_extend*fmin(1.0, scene.driver_pose_diff[0] * 5.0), Qt::SolidLine, Qt::RoundCap));
  painter.drawArc(QRectF(x - arc_l / 2, std::fmin(y + delta_y, y), arc_l, fabs(delta_y)), (scene.driver_pose_sins[0]>0 ? 0 : 180) * 16, 180 * 16);

  painter.restore();
}

void AnnotatedCameraWidget::drawLead(QPainter &painter, const cereal::RadarState::LeadData::Reader &lead_data, const QPointF &vd) {
  painter.save();

  const float speedBuff = 10.;
  const float leadBuff = 40.;
  const float d_rel = lead_data.getDRel();
  const float v_rel = lead_data.getVRel();

  float fillAlpha = 0;
  if (d_rel < leadBuff) {
    fillAlpha = 255 * (1.0 - (d_rel / leadBuff));
    if (v_rel < 0) {
      fillAlpha += 255 * (-1 * (v_rel / speedBuff));
    }
    fillAlpha = (int)(fmin(fillAlpha, 255));
  }

  float sz = std::clamp((25 * 30) / (d_rel / 3 + 30), 15.0f, 30.0f) * 2.35;
  float x = std::clamp((float)vd.x(), 0.f, width() - sz / 2);
  float y = std::fmin(height() - sz * .6, (float)vd.y());

  float g_xo = sz / 5;
  float g_yo = sz / 10;

  QPointF glow[] = {{x + (sz * 1.35) + g_xo, y + sz + g_yo}, {x, y - g_yo}, {x - (sz * 1.35) - g_xo, y + sz + g_yo}};
  painter.setBrush(QColor(218, 202, 37, 255));
  painter.drawPolygon(glow, std::size(glow));

  // chevron
  QPointF chevron[] = {{x + (sz * 1.25), y + sz}, {x, y}, {x - (sz * 1.25), y + sz}};
  painter.setBrush(redColor(fillAlpha));
  painter.drawPolygon(chevron, std::size(chevron));

  painter.restore();
}

void AnnotatedCameraWidget::paintGL() {
  UIState *s = uiState();
  SubMaster &sm = *(s->sm);
  const double start_draw_t = millis_since_boot();
  const cereal::ModelDataV2::Reader &model = sm["modelV2"].getModelV2();

  // draw camera frame
  {
    std::lock_guard lk(frame_lock);

    if (frames.empty()) {
      if (skip_frame_count > 0) {
        skip_frame_count--;
        qDebug() << "skipping frame, not ready";
        return;
      }
    } else {
      // skip drawing up to this many frames if we're
      // missing camera frames. this smooths out the
      // transitions from the narrow and wide cameras
      skip_frame_count = 5;
    }

    // Wide or narrow cam dependent on speed
    bool has_wide_cam = available_streams.count(VISION_STREAM_WIDE_ROAD);
    if (has_wide_cam) {
      float v_ego = sm["carState"].getCarState().getVEgo();
      if ((v_ego < 10) || available_streams.size() == 1) {
        wide_cam_requested = true;
      } else if (v_ego > 15) {
        wide_cam_requested = false;
      }
      wide_cam_requested = wide_cam_requested && sm["controlsState"].getControlsState().getExperimentalMode();
      // for replay of old routes, never go to widecam
      wide_cam_requested = wide_cam_requested && s->scene.calibration_wide_valid;
    }
    CameraWidget::setStreamType(wide_cam_requested ? VISION_STREAM_WIDE_ROAD : VISION_STREAM_ROAD);

    s->scene.wide_cam = CameraWidget::getStreamType() == VISION_STREAM_WIDE_ROAD;
    if (s->scene.calibration_valid) {
      auto calib = s->scene.wide_cam ? s->scene.view_from_wide_calib : s->scene.view_from_calib;
      CameraWidget::updateCalibration(calib);
    } else {
      CameraWidget::updateCalibration(DEFAULT_CALIBRATION);
    }
    CameraWidget::setFrameId(model.getFrameId());
    CameraWidget::paintGL();
  }

  QPainter painter(this);
  painter.setRenderHint(QPainter::Antialiasing);
  painter.setPen(Qt::NoPen);

  if (s->scene.world_objects_visible) {
    update_model(s, model);
    drawLaneLines(painter, s);

    if (s->scene.longitudinal_control && sm.rcv_frame("radarState") > s->scene.started_frame) {
      auto radar_state = sm["radarState"].getRadarState();
      update_leads(s, radar_state, model.getPosition());
      auto lead_one = radar_state.getLeadOne();
      auto lead_two = radar_state.getLeadTwo();
      if (lead_one.getStatus()) {
        drawLead(painter, lead_one, s->scene.lead_vertices[0]);
      }
      if (lead_two.getStatus() && (std::abs(lead_one.getDRel() - lead_two.getDRel()) > 3.0)) {
        drawLead(painter, lead_two, s->scene.lead_vertices[1]);
      }
    }
  }

  // DMoji
  if (!hideBottomIcons && (sm.rcv_frame("driverStateV2") > s->scene.started_frame)) {
    update_dmonitoring(s, sm["driverStateV2"].getDriverStateV2(), dm_fade_state, rightHandDM);
    drawDriverState(painter, s);
  }

  drawHud(painter);

  double cur_draw_t = millis_since_boot();
  double dt = cur_draw_t - prev_draw_t;
  double fps = fps_filter.update(1. / dt * 1000);
  if (fps < 15) {
    LOGW("slow frame rate: %.2f fps", fps);
  }
  prev_draw_t = cur_draw_t;

  // publish debug msg
  MessageBuilder msg;
  auto m = msg.initEvent().initUiDebug();
  m.setDrawTimeMillis(cur_draw_t - start_draw_t);
  pm->send("uiDebug", msg);
}

void AnnotatedCameraWidget::showEvent(QShowEvent *event) {
  CameraWidget::showEvent(event);

  ui_update_params(uiState());
  prev_draw_t = millis_since_boot();
}
